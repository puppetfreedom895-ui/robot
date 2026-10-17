"""界面树压缩：只保留能看懂和能点的元素。"""

from __future__ import annotations

from robot.phone.ui import diff_nodes, format_node, format_screen, parse_hierarchy

SCREEN_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" text="" content-desc="" clickable="false"
        scrollable="false" resource-id="" bounds="[0,0][1080,2400]" visible-to-user="true"
        package="com.android.settings">
    <node class="android.widget.EditText" text="" content-desc="搜索设置"
          clickable="true" resource-id="com.android.settings:id/search"
          bounds="[40,120][1040,260]" visible-to-user="true"/>
    <node class="android.widget.TextView" text="WLAN" content-desc=""
          clickable="false" resource-id="com.android.settings:id/title"
          bounds="[60,300][1020,400]" visible-to-user="true"/>
    <node class="android.widget.Button" text="关闭" content-desc=""
          clickable="true" resource-id="android:id/button1"
          bounds="[800,500][1000,600]" visible-to-user="true"/>
    <node class="android.widget.TextView" text="看不见的东西" content-desc=""
          clickable="false" bounds="[0,0][10,10]" visible-to-user="false"/>
  </node>
</hierarchy>
"""


def test_parse_keeps_actionable_and_text_nodes() -> None:
    nodes = parse_hierarchy(SCREEN_XML)
    assert len(nodes) == 3
    assert [node.label for node in nodes] == ["搜索设置", "WLAN", "关闭"]


def test_parse_numbers_from_one_in_screen_order() -> None:
    nodes = parse_hierarchy(SCREEN_XML)
    assert [node.index for node in nodes] == [1, 2, 3]


def test_parse_assigns_readable_kinds() -> None:
    nodes = parse_hierarchy(SCREEN_XML)
    assert nodes[0].kind == "输入框"
    assert nodes[1].kind == "文本"
    assert nodes[2].kind == "按钮"


def test_node_center_is_tappable_point() -> None:
    nodes = parse_hierarchy(SCREEN_XML)
    assert nodes[2].center == (900, 550)


def test_hidden_nodes_are_dropped() -> None:
    labels = [node.label for node in parse_hierarchy(SCREEN_XML)]
    assert "看不见的东西" not in labels


def test_format_node_is_compact() -> None:
    node = parse_hierarchy(SCREEN_XML)[0]
    assert format_node(node) == "#1 输入框「搜索设置」"


def test_format_node_falls_back_to_resource_id() -> None:
    xml = """<hierarchy><node class="android.widget.ImageButton" text="" content-desc=""
        clickable="true" resource-id="com.app:id/more" bounds="[0,0][100,100]"
        visible-to-user="true"/></hierarchy>"""
    nodes = parse_hierarchy(xml)
    assert nodes[0].label == ""
    assert "more" in format_node(nodes[0])


def test_format_screen_respects_char_budget() -> None:
    nodes = parse_hierarchy(SCREEN_XML)
    text = format_screen(nodes, header="com.android.settings", max_chars=30)
    assert len(text) <= 30
    assert "还有" in text


def test_format_screen_reports_nothing_readable() -> None:
    assert "没有可读的元素" in format_screen([], header="")


def test_diff_detects_added_and_removed() -> None:
    old = parse_hierarchy(SCREEN_XML)
    new = parse_hierarchy(SCREEN_XML.replace("WLAN", "蓝牙").replace("关闭", "打开"))
    diff = diff_nodes(old, new)
    assert "界面已变化" in diff
    assert "蓝牙" in diff


def test_diff_reports_no_change() -> None:
    nodes = parse_hierarchy(SCREEN_XML)
    assert diff_nodes(nodes, nodes) == "界面没有变化"


def test_malformed_xml_is_tolerated() -> None:
    assert parse_hierarchy("<hierarchy>没闭合") == []
