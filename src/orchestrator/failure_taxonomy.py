"""失败分类体系

定义系统可能遇到的各种失败类型，让失败处理更精细、更有针对性。
"""

from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    """失败类型分类"""

    # 格式相关
    FORMAT_ERROR = "format_error"  # 输出格式不符合要求
    MISSING_FIELD = "missing_field"  # 缺少必要字段
    INVALID_TYPE = "invalid_type"  # 类型错误

    # 内容相关
    INSUFFICIENT_CONTENT = "insufficient_content"  # 内容不足
    EMPTY_OUTPUT = "empty_output"  # 输出为空
    QUALITY_BELOW_THRESHOLD = "quality_below_threshold"  # 质量不达标

    # 评估相关
    EVALUATION_FAILED = "evaluation_failed"  # 评估未通过
    RETRY_EXHAUSTED = "retry_exhausted"  # 重试次数耗尽

    # 安全相关
    GUARDRAIL_BLOCKED = "guardrail_blocked"  # 护栏拦截
    PERMISSION_DENIED = "permission_denied"  # 权限不足
    TRUST_LEVEL_INSUFFICIENT = "trust_level_insufficient"  # 信任级别不够

    # 执行相关
    TIMEOUT = "timeout"  # 超时
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"  # 超过最大步数
    AGENT_ERROR = "agent_error"  # Agent 执行错误

    # 控制相关
    SUPERVISOR_REJECTED = "supervisor_rejected"  # Supervisor 拒绝
    REPLAN_FAILED = "replan_failed"  # 重规划失败
    CHECKPOINT_RESTORE_FAILED = "checkpoint_restore_failed"  # 检查点恢复失败

    # 外部相关
    TOOL_ERROR = "tool_error"  # 工具执行错误
    LLM_ERROR = "llm_error"  # LLM 调用错误
    EXTERNAL_SERVICE_ERROR = "external_service_error"  # 外部服务错误

    # 未知
    UNKNOWN = "unknown"  # 未知错误


class FailureSeverity(str, Enum):
    """失败严重程度"""

    LOW = "low"  # 低：可以重试
    MEDIUM = "medium"  # 中：需要调整策略
    HIGH = "high"  # 高：需要人工介入
    CRITICAL = "critical"  # 严重：系统级问题


# 失败类型到严重程度的默认映射
DEFAULT_SEVERITY_MAP: dict[FailureCategory, FailureSeverity] = {
    FailureCategory.FORMAT_ERROR: FailureSeverity.LOW,
    FailureCategory.MISSING_FIELD: FailureSeverity.LOW,
    FailureCategory.INVALID_TYPE: FailureSeverity.LOW,
    FailureCategory.INSUFFICIENT_CONTENT: FailureSeverity.MEDIUM,
    FailureCategory.EMPTY_OUTPUT: FailureSeverity.MEDIUM,
    FailureCategory.QUALITY_BELOW_THRESHOLD: FailureSeverity.MEDIUM,
    FailureCategory.EVALUATION_FAILED: FailureSeverity.MEDIUM,
    FailureCategory.RETRY_EXHAUSTED: FailureSeverity.MEDIUM,
    FailureCategory.GUARDRAIL_BLOCKED: FailureSeverity.HIGH,
    FailureCategory.PERMISSION_DENIED: FailureSeverity.HIGH,
    FailureCategory.TRUST_LEVEL_INSUFFICIENT: FailureSeverity.HIGH,
    FailureCategory.TIMEOUT: FailureSeverity.MEDIUM,
    FailureCategory.MAX_STEPS_EXCEEDED: FailureSeverity.MEDIUM,
    FailureCategory.AGENT_ERROR: FailureSeverity.HIGH,
    FailureCategory.SUPERVISOR_REJECTED: FailureSeverity.MEDIUM,
    FailureCategory.REPLAN_FAILED: FailureSeverity.HIGH,
    FailureCategory.CHECKPOINT_RESTORE_FAILED: FailureSeverity.HIGH,
    FailureCategory.TOOL_ERROR: FailureSeverity.MEDIUM,
    FailureCategory.LLM_ERROR: FailureSeverity.HIGH,
    FailureCategory.EXTERNAL_SERVICE_ERROR: FailureSeverity.HIGH,
    FailureCategory.UNKNOWN: FailureSeverity.MEDIUM,
}


class FailureRecord:
    """失败记录"""

    def __init__(
        self,
        category: FailureCategory,
        agent_name: str | None = None,
        reason: str = "",
        severity: FailureSeverity | None = None,
        context: dict[str, Any] | None = None,
    ):
        self.category = category
        self.agent_name = agent_name
        self.reason = reason
        self.severity = severity or DEFAULT_SEVERITY_MAP.get(category, FailureSeverity.MEDIUM)
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "agent_name": self.agent_name,
            "reason": self.reason,
            "severity": self.severity.value,
            "context": self.context,
        }


def create_failure_record(
    *,
    category: FailureCategory,
    agent_name: str | None = None,
    reason: str = "",
    severity: FailureSeverity | None = None,
    context: dict[str, Any] | None = None,
) -> FailureRecord:
    """创建失败记录

    这是推荐的创建 FailureRecord 的方式，让失败源头显式传入 category。

    Args:
        category: 失败类型
        agent_name: 失败的 agent 名称
        reason: 失败原因
        severity: 严重程度（可选，默认根据 category 映射）
        context: 额外上下文

    Returns:
        FailureRecord: 失败记录
    """
    return FailureRecord(
        category=category,
        agent_name=agent_name,
        reason=reason,
        severity=severity,
        context=context,
    )


def infer_failure_category(
    *,
    status: str,
    reason: str,
    event_type: str | None = None,
    eval_action: str | None = None,
) -> FailureCategory:
    """根据运行时信息推断失败类型

    这是一个 fallback 函数，当失败源头没有显式传入 category 时使用。
    优先使用 create_failure_record() 让失败源头显式指定 category。

    Args:
        status: 运行状态（failed, timed_out, guardrail_blocked 等）
        reason: 失败原因
        event_type: 事件类型（从 execution_trace 获取）
        eval_action: 评估动作（retry, fail 等）

    Returns:
        FailureCategory: 推断的失败类型
    """
    # 护栏触发
    if status == "guardrail_blocked" or event_type == "guardrail_violation":
        return FailureCategory.GUARDRAIL_BLOCKED

    # 超时
    if status == "timed_out":
        if "最大步数" in reason or "max_steps" in reason.lower():
            return FailureCategory.MAX_STEPS_EXCEEDED
        return FailureCategory.TIMEOUT

    # 权限相关
    if "trust_level" in reason.lower() or "risk_level" in reason.lower():
        return FailureCategory.TRUST_LEVEL_INSUFFICIENT

    if "permission" in reason.lower() or "权限" in reason:
        return FailureCategory.PERMISSION_DENIED

    # 重试耗尽
    if "重试" in reason or "retry" in reason.lower():
        return FailureCategory.RETRY_EXHAUSTED

    # 评估失败
    if eval_action in ("retry", "fail") or event_type == "evaluation":
        if "必须输出" in reason or "缺少" in reason:
            return FailureCategory.MISSING_FIELD
        if "类型" in reason or "type" in reason.lower():
            return FailureCategory.INVALID_TYPE
        if "数量" in reason or "至少" in reason:
            return FailureCategory.INSUFFICIENT_CONTENT
        return FailureCategory.EVALUATION_FAILED

    # 工具错误
    if "tool" in reason.lower() or "工具" in reason:
        return FailureCategory.TOOL_ERROR

    # Agent 错误
    return FailureCategory.AGENT_ERROR


# 保持向后兼容
def classify_failure(
    *,
    status: str,
    reason: str,
    agent_name: str | None = None,
    event_type: str | None = None,
    eval_action: str | None = None,
) -> FailureRecord:
    """根据失败信息自动分类

    已废弃：优先使用 create_failure_record() 让失败源头显式指定 category。
    此函数保留用于向后兼容和 fallback。

    Args:
        status: 运行状态（failed, timed_out, guardrail_blocked 等）
        reason: 失败原因
        agent_name: 失败的 agent 名称
        event_type: 事件类型（从 execution_trace 获取）
        eval_action: 评估动作（retry, fail 等）

    Returns:
        FailureRecord: 分类后的失败记录
    """
    category = infer_failure_category(
        status=status,
        reason=reason,
        event_type=event_type,
        eval_action=eval_action,
    )
    return FailureRecord(
        category=category,
        agent_name=agent_name,
        reason=reason,
    )
