"""Runs the proof-reading stage: estimate, ask, check, apply, report."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from . import cost as cost_module
from . import prompt as prompt_module
from .apply import decide
from .document import (
    ProofreadDocument,
    apply_italics,
    document_from_pair,
    document_from_srt_file,
    target_to_internal,
)
from .models import (
    BackendError,
    BackendUsage,
    Patch,
    ProofreadError,
    RejectedPatch,
)
from .report import ProofreadReport, write_report

LOG = logging.getLogger(__name__)


@dataclass
class ProofreadOptions:
    """Everything the stage is allowed to decide for itself."""

    model: str = "gemini-3.8-flash"
    thinking_level: str = "medium"
    min_severity: str = "minor"
    max_change_fraction: float = 0.30
    max_length_growth: float = 0.25
    target_cps: float = 17.0
    max_cost_usd: float = 0.50
    dry_run: bool = False
    #: Above this estimated prompt size the transcript is cached once and
    #: reviewed in several calls instead of one.
    batch_token_threshold: int = 150_000
    batch_max_cues: int = 400
    cache_ttl_seconds: int = 600
    report_path: str | None = None
    wrap_limit: int = 50
    max_lines: int = 2


@dataclass
class ProofreadResult:
    """What the stage did, in a form the CLI can print and a report can hold."""

    status: str = "skipped"
    applied: list[Patch] = field(default_factory=list)
    rejected: list[RejectedPatch] = field(default_factory=list)
    usage: BackendUsage | None = None
    cost_usd: float | None = None
    model: str = ""
    prompt_digest: str = ""
    batches: int = 0
    error: str = ""
    abort_reason: str = ""
    report_path: str = ""
    estimate: cost_module.CostEstimate | None = None

    @property
    def changed(self) -> bool:
        return self.status == "applied" and bool(self.applied)

    def summary(self) -> str:
        if self.status == "error":
            return f"proof-reading failed: {self.error}"
        if self.status == "skipped":
            return f"proof-reading skipped: {self.error or 'nothing to do'}"
        if self.status == "aborted":
            return f"proof-reading aborted: {self.abort_reason}"

        parts = [f"{len(self.applied)} applied", f"{len(self.rejected)} rejected"]
        if self.usage is not None:
            parts.append(
                f"{self.usage.prompt_tokens + self.usage.output_tokens + self.usage.thoughts_tokens}"
                " tokens"
            )
        if self.cost_usd is not None:
            parts.append(f"${self.cost_usd:.3f}")
        prefix = "proof-reading (dry run)" if self.status == "dry_run" else "proof-reading"
        return f"{prefix}: {', '.join(parts)}"


def plan_batches(document: ProofreadDocument, max_cues: int) -> list[tuple[int, int]]:
    """Scene-aligned id ranges, each no longer than ``max_cues`` cues.

    Batches never split a scene, because a reviewer that can see only half of an
    exchange is back to the blind spot the stage exists to close.
    """
    cues = document.cues
    if not cues:
        return []

    boundaries = list(document.scene_starts) or [0]
    if boundaries[0] != 0:
        boundaries.insert(0, 0)
    boundaries.append(len(cues))

    batches: list[tuple[int, int]] = []
    start = 0
    filled = 0

    for index in range(1, len(boundaries)):
        scene_end = boundaries[index]
        overflows = scene_end - start > max_cues
        # A scene longer than the whole batch budget still goes out in one piece,
        # because splitting an exchange is worse than a large call.
        if overflows and filled > start:
            batches.append((cues[start].id, cues[filled - 1].id))
            start = filled
        filled = scene_end

    if start < len(cues):
        batches.append((cues[start].id, cues[-1].id))
    return batches


def run_proofread(
    document: ProofreadDocument,
    backend,
    options: ProofreadOptions,
) -> ProofreadResult:
    """Review a document and decide which corrections may be applied.

    Nothing is written to the subtitles here. A failure of the model, the schema
    or the guards leaves the translation exactly as it was and is reported.
    """
    result = ProofreadResult(model=getattr(backend, "model", options.model))

    system_instruction = prompt_module.build_system_instruction(
        document.source_lang, document.target_lang
    )
    result.prompt_digest = prompt_module.prompt_digest(system_instruction)

    if not document.cues:
        result.status = "skipped"
        result.error = "no subtitles to review"
        return result

    transcript = prompt_module.build_transcript(document)

    batches = [None]
    single_call_estimate = cost_module.estimate(
        transcript, result.model, source_lang=document.target_lang
    )
    if single_call_estimate.prompt_tokens > options.batch_token_threshold:
        batches = plan_batches(document, options.batch_max_cues) or [None]

    estimate = cost_module.estimate(
        transcript, result.model, source_lang=document.target_lang, calls=len(batches)
    )
    result.batches = len(batches)

    if (
        options.max_cost_usd > 0
        and estimate.cost_usd is not None
        and estimate.cost_usd > options.max_cost_usd
    ):
        result.status = "skipped"
        result.error = (
            f"estimated cost ${estimate.cost_usd:.2f} is over the "
            f"${options.max_cost_usd:.2f} limit (raise it with --proofread-max-cost)"
        )
        result.estimate = estimate
        return result

    LOG.info(
        "Proof-reading %d cues in %d call(s) with %s, estimated %d prompt tokens%s",
        len(document.cues),
        len(batches),
        result.model,
        estimate.prompt_tokens,
        "" if estimate.cost_usd is None else f", about ${estimate.cost_usd:.3f}",
    )

    try:
        from .schema import parse_response, response_schema
    except ImportError as error:
        result.status = "error"
        result.error = f"pydantic is required for proof-reading: {error}"
        result.estimate = estimate
        return result

    cache_name: str | None = None
    raw_patches: list[dict] = []
    usage = BackendUsage()

    try:
        if len(batches) > 1:
            cache_name = backend.create_cached_prefix(
                system_instruction, transcript, options.cache_ttl_seconds
            )

        for id_range in batches:
            if id_range is None:
                user_content = transcript
            elif cache_name:
                user_content = prompt_module.range_instruction(*id_range)
            else:
                user_content = prompt_module.build_user_content(document, id_range)

            response = backend.review(
                system_instruction,
                user_content,
                response_schema=response_schema(),
                cached_content=cache_name,
            )
            raw_patches.extend(response.patches)
            usage = usage + response.usage
            if response.model:
                result.model = response.model
    except (BackendError, ProofreadError) as error:
        result.status = "error"
        result.error = str(error)
        result.usage = usage
        result.estimate = estimate
        return result
    except Exception as error:  # noqa: BLE001 - never lose a paid translation to this stage
        result.status = "error"
        result.error = f"{type(error).__name__}: {error}"
        result.usage = usage
        result.estimate = estimate
        return result
    finally:
        if cache_name:
            backend.delete_cached_prefix(cache_name)

    result.usage = usage
    result.cost_usd = cost_module.compute_cost(usage, result.model)
    result.estimate = estimate

    try:
        patches = parse_response({"patches": raw_patches})
    except ValueError as error:
        # A partially understood answer is not applied at all: a patch whose
        # fields we had to guess is exactly the kind that corrupts a subtitle.
        result.status = "error"
        result.error = str(error)
        return result

    decision = decide(
        document,
        patches,
        min_severity=options.min_severity,
        max_growth=options.max_length_growth,
        target_cps=options.target_cps,
        max_change_fraction=options.max_change_fraction,
    )
    result.rejected = decision.rejected

    if decision.aborted:
        result.status = "aborted"
        result.abort_reason = decision.abort_reason
        return result

    result.applied = decision.accepted
    result.status = "dry_run" if options.dry_run else "applied"
    return result


def _build_report(
    document: ProofreadDocument,
    result: ProofreadResult,
    options: ProofreadOptions,
    input_path: str,
    source_path: str = "",
) -> ProofreadReport:
    estimate = result.estimate
    return ProofreadReport(
        status=result.status,
        model=result.model,
        thinking_level=options.thinking_level,
        prompt_digest=result.prompt_digest,
        input_path=input_path,
        source_path=source_path,
        source_lang=document.source_lang,
        target_lang=document.target_lang,
        cues=len(document.cues),
        scenes=len(document.scene_starts),
        batches=result.batches,
        estimate={} if estimate is None else estimate.to_dict(),
        usage=result.usage,
        cost_usd=result.cost_usd,
        applied=result.applied,
        rejected=result.rejected,
        error=result.error,
        abort_reason=result.abort_reason,
    )


def _report_path(options: ProofreadOptions, default_for: str, *protected: str) -> str:
    """Where the report goes, refusing any path that would destroy a subtitle.

    The report is written with mode "w". Pointed at one of the subtitles it would
    replace it with JSON, and a dry run would do it too, so this is checked before
    the model is called rather than after.
    """
    path = options.report_path or f"{default_for}.proofread.json"

    resolved = os.path.abspath(path)
    for candidate in protected:
        if candidate and os.path.abspath(candidate) == resolved:
            raise ProofreadError(
                f"--proofread-report would overwrite {os.path.basename(candidate)}. "
                "Choose a path that is not one of the subtitle files."
            )
    return path


def _write_report_safely(report: ProofreadReport, path: str) -> str:
    """Write the report, but never let its failure undo the work it describes."""
    try:
        return write_report(report, path)
    except OSError as error:
        LOG.error("Could not write the proof-reading report to %s: %s", path, error)
        return ""


def proofread_srt_file(
    sub,
    backend,
    options: ProofreadOptions,
    source_lang: str,
    target_lang: str,
    *,
    report_for: str = "",
) -> ProofreadResult:
    """Review an in-flight SrtFile and write the accepted corrections into it.

    Call this after translate() and before wrapping: the cue text is still one
    line per cue, and the source text is still available to compare against.
    """
    report_path = _report_path(options, report_for or sub.filepath, sub.filepath)

    document = document_from_srt_file(sub, source_lang, target_lang)
    result = run_proofread(document, backend, options)

    if result.status == "applied" and result.applied:
        by_index = {subtitle.index: subtitle for subtitle in sub.subtitles}
        by_id = document.by_id()
        for patch in result.applied:
            subtitle = by_index.get(patch.id)
            cue = by_id.get(patch.id)
            if subtitle is None or cue is None:
                continue
            subtitle.content = apply_italics(
                target_to_internal(patch.after, cue.is_dialogue), cue.italics
            )

    result.report_path = _write_report_safely(
        _build_report(document, result, options, sub.filepath), report_path
    )
    return result


def proofread_pair(
    source_path: str,
    translated_path: str,
    backend,
    options: ProofreadOptions,
    source_lang: str,
    target_lang: str,
    *,
    output_path: str | None = None,
    backup: bool = True,
) -> ProofreadResult:
    """Review a finished translation against its original and rewrite it.

    This is the standalone workflow: it takes a subtitle that has already been
    translated, and optionally already mechanically fixed, and corrects only what
    the review finds wrong with its meaning.
    """
    import shutil

    import srt as srt_module

    destination = output_path or translated_path
    report_path = _report_path(
        options,
        destination,
        translated_path,
        source_path,
        destination,
        f"{translated_path}.bak",
    )

    document, translated_subs = document_from_pair(
        source_path, translated_path, source_lang, target_lang
    )
    result = run_proofread(document, backend, options)

    if result.status == "applied" and result.applied:
        by_index = {subtitle.index: subtitle for subtitle in translated_subs}
        by_id = document.by_id()

        width = _observed_line_width(document, options.wrap_limit)
        for patch in result.applied:
            subtitle = by_index.get(patch.id)
            cue = by_id.get(patch.id)
            if subtitle is None or cue is None:
                continue
            subtitle.content = apply_italics(
                _render_for_file(patch.after, width, options.max_lines), cue.italics
            )

        if backup and os.path.abspath(destination) == os.path.abspath(translated_path):
            shutil.copy2(translated_path, f"{translated_path}.bak")

        with open(destination, "w", encoding="utf-8") as handle:
            handle.write(srt_module.compose(translated_subs))
        LOG.info("Wrote %d corrections to %s", len(result.applied), destination)

    result.report_path = _write_report_safely(
        _build_report(document, result, options, translated_path, source_path), report_path
    )
    return result


def _observed_line_width(document: ProofreadDocument, ceiling: int) -> int:
    """How wide the lines of this file already are.

    A finished subtitle has been laid out to some house width. Re-wrapping a
    corrected cue to a different width would make that one cue stand out, so the
    file's own width is used when it is narrower than the configured ceiling.
    """
    widest = max(
        (len(line) for cue in document.cues for line in cue.target.split("\n")),
        default=0,
    )
    if widest < 20:
        return ceiling
    return min(ceiling, widest)


def _render_for_file(text: str, wrap_limit: int, max_lines: int) -> str:
    """Lay out a corrected cue the way the surrounding file is laid out.

    Nothing wraps after this stage in pair mode, so a correction that already
    came back with line breaks keeps them. Only a single long line is wrapped.
    """
    from ..srt_file import SrtFile

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) > 1:
        return "\n".join(lines)

    flat = " ".join(text.split())
    if len(flat) <= wrap_limit:
        return flat
    return SrtFile.wrap_line(flat, wrap_limit, max_lines)
