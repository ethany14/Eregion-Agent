"""Recognize explicit resume commands before a paused agent can call its model."""
import re


def requests_resume(text: str) -> bool:
    value = text.strip().casefold()
    if value in {'continue', 'resume', 'retry', '继续', '继续吧', '恢复', '重试'}:
        return True
    # Later restrictions ("do not submit") do not negate a leading Continue.
    # Explicitly negating execution still holds the pause, even in a later clause.
    if re.search(r"\b(?:not|don't|never)\s+(?:continue|resume|retry|proceed|start|run|go|now|yet)\b"
                 r"|(?:\u4e0d\u8981|\u522b|\u5148\u4e0d)(?:\u7ee7\u7eed|\u6062\u590d|\u91cd\u8bd5|\u5f00\u59cb|\u8fd0\u884c)", value):
        return False
    command_clause = re.split(r'[.!?;\n\u3002\uff01\uff1f\uff1b]', value, maxsplit=1)[0]
    if re.search(r"\b(?:wait|if|when|once|later|tomorrow)\b|\u7a0d\u540e|\u7b49\u6211|\u660e\u5929", command_clause):
        return False
    return bool(re.match(
        r'^(?:(?:please|ok|okay)[,，]?\s+)*(?:continue|resume|retry)\b'
        r'|^(?:请|现在|可以|好的[，,]?\s*)?(?:继续|恢复|重试)(?!等待|暂停)', value))


def resume_command_only(text: str) -> bool:
    """A bare resume preserves pending questions; resume plus feedback answers them."""
    return bool(re.fullmatch(
        r"\s*(?:(?:please|ok|okay)[,\s]+)*(?:continue|resume|retry)(?:\s+now)?[.!\s]*"
        r"|\s*(?:\u8bf7|\u73b0\u5728|\u597d\u7684[\uff0c,]?\s*)?(?:\u7ee7\u7eed\u5427?|\u6062\u590d|\u91cd\u8bd5)[\u3002\uff01!\s]*",
        text.casefold()))


def requests_pause(text: str) -> bool:
    """Recognize an immediate leading pause command with optional follow-up text."""
    value = text.strip().casefold()
    return bool(re.match(
        r'^(?:(?:please|ok|okay)[,\s]+)*(?:pause|stop)'
        r'(?:\s+(?:now|for now|the agent|the task))?(?=$|[.!?,;:\n])'
        r'|^(?:\u8bf7|\u5148|\u73b0\u5728)*(?:\u6682\u505c|\u505c\u6b62)'
        r'(?=$|[\s\u3002\uff0c\uff01.!?,;:]|\u4e00\u4e0b)', value))
