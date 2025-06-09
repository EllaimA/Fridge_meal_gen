# fridge_recipe_generator.py
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import List, Dict

import pandas as pd
import streamlit as st
from openai import OpenAI

DATA_PATH = Path("inventory.json")


def load_api_key() -> str | None:
    return (
        os.getenv("OPENAI_API_KEY")
        or st.secrets.get("OPENAI_API_KEY")
        or (st.secrets.get("api") or {}).get("OPENAI_API_KEY")
    )


def ensure_key() -> str:
    key = load_api_key()
    if not key:
        with st.sidebar:
            key = st.text_input("OpenAI API Key", type="password")
    if not key:
        st.stop()
    st.session_state.api_key = key
    return key


def save_inventory(inv: List[Dict]):
    DATA_PATH.write_text(
        json.dumps(inv, ensure_ascii=False, default=str, indent=2), encoding="utf-8"
    )


def load_inventory() -> List[Dict]:
    if not DATA_PATH.exists() or DATA_PATH.stat().st_size == 0:
        return []
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    for item in raw:
        exp = item.get("expiry")
        if isinstance(exp, str):
            try:
                item["expiry"] = date.fromisoformat(exp)
            except ValueError:
                item["expiry"] = pd.to_datetime(exp).date()
        elif isinstance(exp, pd.Timestamp):
            item["expiry"] = exp.date()
    return raw


if "inventory" not in st.session_state:
    st.session_state.inventory = load_inventory()
if "api_key" not in st.session_state:
    st.session_state.api_key = None

st.set_page_config(page_title="智能食谱", layout="wide")

st.title("食谱生成器")

with st.sidebar:
    ensure_key()

with st.form("add_ingredient"):
    cols = st.columns(6)
    name = cols[0].text_input("食材名称", placeholder="如：鸡胸肉")
    qty = cols[1].number_input("数量", min_value=0.0, step=0.1, format="%g")
    unit = cols[2].selectbox("单位", ["g", "kg", "lb", "oz", "ml", "L", "个", "片", "杯", "勺", "份"])
    expiry = cols[3].date_input("到期日", value=date.today())
    category = cols[4].selectbox("分类", ["肉", "菜", "主食", "水果", "酱料", "饮料"], index=1)
    if cols[5].form_submit_button("添加") and name:
        st.session_state.inventory.append(
            {
                "name": name.strip(),
                "quantity": qty,
                "unit": unit,
                "expiry": expiry,
                "category": category,
            }
        )
        save_inventory(st.session_state.inventory)
        st.rerun()

if st.session_state.inventory:
    df = (
        pd.DataFrame(st.session_state.inventory)
        .sort_values(["category", "expiry"])
        .reset_index(drop=True)
    )
    edited_df = st.data_editor(df, key="editor", num_rows="dynamic", use_container_width=True)

    updated_inv: List[Dict] = []
    for row in edited_df.to_dict("records"):
        exp = row["expiry"]
        if isinstance(exp, str):
            try:
                exp = date.fromisoformat(exp)
            except ValueError:
                exp = pd.to_datetime(exp).date()
        elif isinstance(exp, pd.Timestamp):
            exp = exp.date()
        row["expiry"] = exp
        updated_inv.append(row)
    st.session_state.inventory = updated_inv
    save_inventory(updated_inv)

    sel = []
    ed_state = st.session_state.get("editor")
    if isinstance(ed_state, dict):
        sel = ed_state.get("row_selection") or ed_state.get("selected_rows") or []
        sel = [int(i) for i in sel]
else:
    st.info("暂无库存，先添加食材。")

if st.session_state.inventory:
    days = st.selectbox("预设天数", list(range(1, 15)), 0)
    strict = st.checkbox("仅使用现有食材", True)
    if st.button("✨ 生成食谱"):
        with st.spinner("正在生成营养计划…"):
            inv_text = "\n".join(
                f"- {i['name']} ({i['quantity']}{i['unit']}, {i['category']}, expiring {i['expiry']})"
                for i in st.session_state.inventory
            )
            prompt = (
                "You are a registered dietitian and creative home‑cook.\n"
                f"Design a {days}-day meal plan for one male and one female in their 20s.\n\n"

                "【总体要求】\n"
                "1. 每天必须包含 早餐、午餐、晚餐。\n"
                "2. 餐食需营养均衡：足量蛋白质、复合碳水、蔬菜与健康脂肪；晚餐更轻盈、易消化。\n"
                "3. 可使用空气炸锅（首选）、榨汁机、豆浆机；尽量采用低油方式减少油烟。\n"
                "4. **避免把所有蔬菜都切成丝**，可根据需要切块、切片、切丁。\n"
                "5. 用中文输出，采用 Markdown 格式：天次标题和菜名加粗，条目用列表符号。\n\n"

                "【菜品格式（Markdown 示范）】\n"
                "**菜名**\n"
                "  - 食材（g/ml）\n"
                "  - 做法：步骤 1…步骤 3–5\n\n"

                "【配料与库存】\n"
                "下方是冰箱库存清单，请先对比再编排菜单，遵守以下规则：\n"
                + (
                    "  - 不得超出任何食材库存；如有超出请调整菜品使总用量不超库存。\n"
                    if strict else
                    "  - 若所需量超出库存，请在文末新增章节 **需购买的额外食材**，列出不足食材及数量。\n"
                ) + "\n"

                "【每日总结】\n"
                "每天菜单后，用 1–2 句话说明该日如何满足营养需求。\n\n"

                "⚠️ 不要在每道菜后输出类似“【冰箱库存：米饭1000 g，使用后剩 600 g】”的提示。\n\n"

                "=== 冰箱库存 ===\n"
                f"{inv_text}"
            )


            client = OpenAI(api_key=st.session_state.api_key)
            try:
                resp = client.chat.completions.create(
                    model="o3-mini",
                    messages=[
                        {"role": "system", "content": "You are a helpful culinary assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    #temperature=0.7,
                    max_completion_tokens=15000,
                )
                st.markdown(resp.choices[0].message.content.strip())
            except Exception as e:
                st.error(f"OpenAI 调用失败：{e}")
