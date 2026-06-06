"""节点类型注册表。"""
from __future__ import annotations

from enum import Enum

from framework.workflow.flow_type import BaseNode
from framework.workflow.node.end import EndNode
from framework.workflow.node.human_input import HumanInputNode
from framework.workflow.node.start import StartNode
from framework.workflow.node.subgraph import SubGraphNode
from framework.workflow.node.switch import SwitchNode
from framework.workflow.node.tool import ToolNode


class NodeType(str, Enum):
    START = "start"
    END = "end"
    TOOL = "tool"
    SWITCH = "switch"
    SUBGRAPH = "subgraph"
    HUMAN_INPUT = "human_input"


NODE_TYPE_CLASSES_MAPPING: dict[NodeType, type[BaseNode]] = {
    NodeType.START: StartNode,
    NodeType.END: EndNode,
    NodeType.TOOL: ToolNode,
    NodeType.SWITCH: SwitchNode,
    NodeType.SUBGRAPH: SubGraphNode,
    NodeType.HUMAN_INPUT: HumanInputNode,
}
