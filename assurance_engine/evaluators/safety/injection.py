"""safety.injection and safety.file — untrusted-content screening.

Injection detection is a *heuristic* screen over text that may later be placed
in a model's context. A pattern hit is evidence for review, not proof of an
attack, and an absence of hits is not proof of safety (whitepaper 7.4.1:
efficacy requires testing). Findings therefore never carry deterministic
confidence for pattern matches.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ....domain.evaluations import CheckResult, CheckStatus, Confidence, Severity, UnknownReason
from ...normalization.models import iter_text_units
from ..base import EvalContext, finish, make_finding, pointer, unknown

__all__ = ["check_injection", "check_file"]

_FLAGS = re.IGNORECASE

_OVERRIDE = (
    ("override", re.compile(r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|any|your)\b[^.\n]{0,40}\b(?:instructions?|prompts?|rules?|guidelines?|context|constraints?)\b", _FLAGS)),
    ("role_reassign", re.compile(r"\byou\s+are\s+now\b[^.\n]{0,60}\b(?:assistant|ai|model|dan|developer mode|jailbroken|unrestricted)\b", _FLAGS)),
    ("system_prompt_marker", re.compile(r"(?:^|\n)\s*(?:system|developer)\s*(?:prompt|message|instruction)s?\s*[:=]", _FLAGS)),
    ("chat_template_marker", re.compile(r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>|\[/?INST\]|<<\/?SYS>>", _FLAGS)),
    ("prompt_leak", re.compile(r"\b(?:reveal|print|show|repeat|leak|output)\b[^.\n]{0,30}\b(?:system prompt|hidden instructions?|your instructions|initial prompt)\b", _FLAGS)),
    ("concealment", re.compile(r"\bdo not (?:tell|inform|mention|reveal|alert)\b[^.\n]{0,30}\b(?:the )?(?:user|human|operator)\b", _FLAGS)),
)
_TOOL = (
    ("agent_directive", re.compile(r"\b(?:assistant|ai|model|agent|llm)\b[^.\n]{0,40}\b(?:must|should|shall|will|needs? to)\b[^.\n]{0,40}\b(?:call|invoke|execute|run|send|e-?mail|post|upload|delete|forward|transfer)\b", _FLAGS)),
    ("exfiltration_image", re.compile(r"!\[[^\]\n]{0,80}\]\(\s*https?://[^)\s]{1,200}\?[^)\s]*(?:\{|\$\{|%7[Bb]|data=|payload=|secret|token|q=)[^)\s]*\)", _FLAGS)),
    ("exfiltration_instruction", re.compile(r"\b(?:send|post|upload|forward|exfiltrate)\b[^.\n]{0,50}\b(?:conversation|chat history|user data|credentials|api keys?|secrets?|contents? of)\b[^.\n]{0,60}\b(?:to|at)\b[^.\n]{0,20}(?:https?://|\w+@\w+)", _FLAGS)),
)
_SHELL_PIPE = re.compile(r"\b(?:curl|wget)\b[^|\n]{1,200}\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b", _FLAGS)
_BIDI = re.compile("[‪-‮⁦-⁩]")
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")
_TAGS = re.compile("[\U000e0000-\U000e007f]")
_INSTR_WORDS = re.compile(r"\b(?:ignore|disregard|instruction|system prompt|you must|assistant|override)\b", _FLAGS)

MAX_TOTAL = 20_000_000


def check_injection(ctx: EvalContext) -> CheckResult:
    hits: dict[tuple[str, str], list] = defaultdict(list)
    scanned = total = 0
    for unit in iter_text_units(ctx.norm):
        total += len(unit.text)
        if scanned >= MAX_TOTAL:
            continue
        scanned += len(unit.text)
        t = unit.text
        for name, rx in _OVERRIDE:
            for m in rx.finditer(t):
                hits[("override", name)].append((unit.path, t, m.start(), m.end()))
        for name, rx in _TOOL:
            for m in rx.finditer(t):
                hits[("tool", name)].append((unit.path, t, m.start(), m.end()))
        for m in _SHELL_PIPE.finditer(t):
            hits[("shell", "pipe_to_shell")].append((unit.path, t, m.start(), m.end()))
        for m in _BIDI.finditer(t):
            hits[("char", "bidi")].append((unit.path, t, m.start(), m.end()))
        for m in _TAGS.finditer(t):
            hits[("char", "tags")].append((unit.path, t, m.start(), m.end()))
        zw = list(_ZERO_WIDTH.finditer(t))
        if len(zw) > 5:
            hits[("char", "zero_width")].extend((unit.path, t, m.start(), m.end()) for m in zw[:3])
    findings = []
    spec = {
        ("override",): (Severity.HIGH, "Embedded instructions addressed to an AI system",
                        "Text that tries to override or redirect an AI system's instructions. A document normally describes; "
                        "it does not instruct the model reading it."),
        ("tool",): (Severity.CRITICAL, "Embedded tool or data-exfiltration directive",
                    "Text that directs an AI agent to act or to send data elsewhere."),
    }
    for (kind, name), items in sorted(hits.items()):
        ptrs = [pointer(path, t, a, b) for path, t, a, b in items[:5]]
        if kind == "override":
            sev, title, inf = spec[("override",)]
            code = f"safety.injection.override.{name}"
            conf = Confidence.heuristic(None, "pattern match; efficacy against novel phrasing is untested")
        elif kind == "tool":
            sev, title, inf = spec[("tool",)]
            code = "safety.injection.tool" if name == "agent_directive" else f"safety.injection.tool.{name}"
            conf = Confidence.heuristic(None, "pattern match; may be a legitimate description of agent behaviour")
        elif kind == "shell":
            sev, title = Severity.MEDIUM, "Download-and-execute command in content"
            inf = "A command that pipes a download into a shell. Common in install docs; dangerous if an agent executes it."
            code, conf = "safety.injection.shell_pipe", Confidence.deterministic()
        elif name == "bidi":
            sev, title = Severity.MEDIUM, "Bidirectional text control characters"
            inf, code, conf = ("Bidi controls can make displayed text differ from the text a model reads.",
                               "safety.injection.bidi_control", Confidence.deterministic())
        elif name == "tags":
            sev, title = Severity.HIGH, "Invisible Unicode tag characters"
            inf, code, conf = ("Tag characters can smuggle hidden ASCII instructions that humans cannot see.",
                               "safety.injection.tag_characters", Confidence.deterministic())
        else:
            sev, title = Severity.MEDIUM, "Invisible zero-width characters"
            inf, code, conf = ("An unusual number of zero-width characters can hide or split text from review.",
                               "safety.injection.invisible_text", Confidence.deterministic())
        findings.append(make_finding(
            "safety.injection", code, title, sev, f"{len(items)} occurrence(s) matching '{name}'", inf, conf,
            "Remove the content or have a security reviewer assess it; do not index it unreviewed.",
            pointers=ptrs, count=len(items), tags=["injection", kind], data={"pattern": name}))
    hidden = list((ctx.norm.html or {}).get("hidden_text") or []) + list(ctx.norm.detection.get("hidden_text") or [])
    if hidden:
        suspicious = [h for h in hidden if _INSTR_WORDS.search(h)]
        findings.append(make_finding(
            "safety.injection", "safety.injection.hidden_text",
            "Hidden text" + (" containing instruction-like words" if suspicious else ""),
            Severity.HIGH if suspicious else Severity.MEDIUM,
            f"{len(hidden)} hidden text element(s) (display:none, hidden, zero font size, Word 'hidden' formatting or similar)",
            "Hidden text is read by models and scrapers but not by people reviewing the page.",
            Confidence.deterministic(), "Remove hidden elements or confirm they are intentional.",
            count=len(hidden), tags=["injection", "hidden"], data={"instruction_like": len(suspicious)}))
    return finish(ctx, "safety.injection", findings, coverage=1.0 if total == 0 else min(1.0, scanned / total),
                  metrics={"scanned_chars": scanned}, name="aidap.safety.injection_patterns")


def _document_findings(a: dict, fmt: str) -> list:
    """What a PDF or Word file contains besides text: scripts, macros, embedded files, remote references."""
    out = []
    if fmt == "pdf":
        active = int(a.get("javascript", 0)) + int(a.get("launch", 0))
        if active:
            out.append(make_finding(
                "safety.file", "safety.file.active_content", "PDF contains scripts or launch actions", Severity.HIGH,
                f"JavaScript actions: {a.get('javascript', 0)}; launch actions: {a.get('launch', 0)}"
                + ("; runs on open" if a.get("open_action") else ""),
                "Scripts and launch actions run in some PDF viewers. They are not needed in a document used as data.",
                Confidence.deterministic("PDF object structure and bytes"),
                "Export a clean copy of the document (print to PDF or save as text) and resubmit.", tags=["pdf", "active"]))
        if a.get("embedded_files"):
            out.append(make_finding(
                "safety.file", "safety.file.embedded_files", "PDF contains embedded files", Severity.MEDIUM,
                f"{a.get('embedded_files')} attached file(s)",
                "Attachments are not opened or assessed, so part of what would be released is unchecked.",
                Confidence.deterministic("PDF object structure"), "Submit the attachments separately, or remove them.",
                tags=["pdf", "embedded"]))
        if a.get("xfa"):
            out.append(make_finding(
                "safety.file", "safety.file.active_content", "PDF contains an XFA form", Severity.MEDIUM,
                "XFA form definition present", "XFA forms are scriptable XML forms that this version does not assess.",
                Confidence.deterministic("PDF object structure"), "Flatten the form before submitting.", tags=["pdf", "form"]))
    elif fmt == "docx":
        if a.get("macros"):
            out.append(make_finding(
                "safety.file", "safety.file.macros", "Word document contains macros", Severity.HIGH,
                "VBA project or macro-enabled content type present",
                "Macros are code. They are not needed in a document used as data and are a common malware route.",
                Confidence.deterministic("package members"), "Save a copy without macros and resubmit.", tags=["docx", "macro"]))
        if a.get("remote_template"):
            out.append(make_finding(
                "safety.file", "safety.file.external_reference", "Word document loads a remote template", Severity.HIGH,
                "attachedTemplate relationship points to an external location",
                "A remote template is fetched when the document opens and can bring in macros from elsewhere.",
                Confidence.deterministic("package relationships"), "Remove the template link and resubmit.", tags=["docx", "remote"]))
        elif a.get("external_links"):
            out.append(make_finding(
                "safety.file", "safety.file.external_reference", "Word document references external content", Severity.LOW,
                f"{a.get('external_links')} external relationship(s) (links, linked images or objects)",
                "Linked content is not part of the file and is not assessed.",
                Confidence.deterministic("package relationships"), "Embed or remove linked content.", tags=["docx", "link"]))
        objs = int(a.get("embedded_objects", 0)) + int(a.get("activex", 0))
        if objs:
            out.append(make_finding(
                "safety.file", "safety.file.embedded_files", "Word document contains embedded objects", Severity.MEDIUM,
                f"{a.get('embedded_objects', 0)} embedded object(s), {a.get('activex', 0)} ActiveX control(s)",
                "Embedded objects are not opened or assessed, so part of what would be released is unchecked.",
                Confidence.deterministic("package members"), "Remove the objects or submit them separately.", tags=["docx", "embedded"]))
    return out


def check_file(ctx: EvalContext) -> CheckResult:
    n, det = ctx.norm, ctx.norm.detection
    findings = []
    risk = det.get("risk_class", "")
    label = det.get("binary_label") or "binary data"
    if det.get("eicar") or (ctx.av or {}).get("status") == "infected":
        sig = (ctx.av or {}).get("signature") or ("EICAR test signature" if det.get("eicar") else "")
        findings.append(make_finding(
            "safety.file", "safety.malicious.malware", "Malware signature detected", Severity.CRITICAL,
            f"Scanner reported: {sig or 'infected'}", "The file matches a known malicious signature.",
            Confidence.deterministic("signature match"),
            "Keep the artifact quarantined and investigate where it came from.", tags=["malware", "non-waivable"]))
    elif risk == "executable":
        findings.append(make_finding(
            "safety.file", "safety.malicious.executable", "Executable file submitted as data", Severity.CRITICAL,
            f"File content is {label}", "Executables are not a valid AI input and cannot be inspected safely here.",
            Confidence.deterministic("magic bytes"), "Do not run or open it. Obtain the data from its owner.",
            tags=["executable", "non-waivable"]))
    elif risk == "script":
        findings.append(make_finding(
            "safety.file", "safety.file.script", "Script submitted as data", Severity.HIGH, f"File content is {label}",
            "A script is code, not data.", Confidence.deterministic("shebang"), "Submit the data, not the script.",
            tags=["script"]))
    elif risk == "macro_container":
        findings.append(make_finding(
            "safety.file", "safety.file.macro_container", "Legacy Office container", Severity.HIGH, f"File content is {label}",
            "Legacy Office containers can carry macros; AIDAP does not open them.", Confidence.deterministic("magic bytes"),
            "Export to text or CSV from a trusted system and resubmit.", tags=["office"]))
    elif risk == "archive" and not n.detection.get("document"):
        findings.append(make_finding(
            "safety.file", "safety.file.archive", "Archive or container file", Severity.MEDIUM, f"File content is {label}",
            "Archives are not opened in this version, so their content is not assessed.", Confidence.deterministic("magic bytes"),
            "Extract trusted files and submit them individually.", tags=["archive"]))
    elif n.detection.get("document"):
        pass                                           # PDF/DOCX read by the document reader; judged below on what they contain
    elif risk in ("document", "image", "database", "binary"):
        findings.append(make_finding(
            "safety.file", "safety.file.unsupported_binary", "Unsupported binary format", Severity.LOW,
            f"File content is {label}", "Not a supported input format; see the intake check.",
            Confidence.deterministic("magic bytes"), "Convert to a supported text format and resubmit.", tags=["binary"]))
    h = n.html or {}
    if h.get("scripts") or h.get("event_handlers") or h.get("js_urls") or h.get("iframes"):
        findings.append(make_finding(
            "safety.file", "safety.file.active_content", "Active content in HTML", Severity.MEDIUM,
            f"scripts={h.get('scripts', 0)}, event handlers={h.get('event_handlers', 0)}, "
            f"javascript: URLs={h.get('js_urls', 0)}, embedded frames={h.get('iframes', 0)}",
            "Active content is stripped from the normalized text but should not be passed on.",
            Confidence.deterministic(), "Submit the content without scripts or embedded frames.", tags=["html"]))
    findings += _document_findings(n.detection.get("active_content") or {}, det.get("format", ""))
    if det.get("mismatch"):
        findings.append(make_finding(
            "safety.file", "safety.file.type_mismatch", "Declared type differs from content", Severity.LOW,
            det["mismatch"], "The submitter's label cannot be trusted for this file.", Confidence.deterministic(),
            "Correct the declared type.", tags=["mismatch"]))
    av = ctx.av or {}
    status = av.get("status", "unavailable")
    metrics = {"av_status": status, "av_engine": av.get("engine", "")}
    if status != "clean" and ctx.policy.require_av_scan:
        res = unknown(ctx, "safety.file", UnknownReason.RUNTIME_UNAVAILABLE,
                      "The policy requires an antivirus scan and none completed; this is not a clean result.",
                      name="aidap.safety.file")
        res.findings = findings
        res.metrics = metrics
        if any(f.severity > Severity.INFO for f in findings):
            res.status = CheckStatus.FAILED
        return res
    if status != "clean":
        findings.append(make_finding(
            "safety.file", "safety.file.av_not_scanned", "No antivirus engine scanned this file", Severity.INFO,
            f"Scanner status: {status}", "Format and signature checks ran; an AV engine did not.",
            Confidence.unknown("scanner unavailable"), "Configure an AV engine to enable malware scanning.",
            tags=["av"]))
    return finish(ctx, "safety.file", findings, coverage=1.0, metrics=metrics, name="aidap.safety.file")
