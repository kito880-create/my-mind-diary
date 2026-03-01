import streamlit as st
import google.generativeai as genai
import sqlite3
import plotly.graph_objects as go
import json
from datetime import datetime
import pandas as pd
import requests
import time
import streamlit.components.v1 as components
import shutil
import os

# --- SECTION 1: Configuration & Constants ---

CHARACTERS = {
    "감정": "몽글이",
    "활동": "꼼지",
    "신체": "콩알이",
    "리듬": "깜빡이",
    "실행": "반짝이",
    "감사": "성냥"
}

EMOTIONS_MAIN = ["우울", "불안", "무기력함", "긴장감", "짜증", "분노", "자책", "공포"]
EMOTIONS_OTHER = ["기쁨", "슬픔", "두려움", "평온", "초조", "죄책감", "부끄러움", "외로움", "혼란", "절망감", "안도감", "만족감", "질투"]
ALL_EMOTIONS = EMOTIONS_MAIN + EMOTIONS_OTHER

PHYSICAL_REACTIONS = [
    "심장 빨라짐", "손에 땀이 남", "근육 긴장", "답답함", "떨림", "두통", "소화불량", 
    "어지러움", "숨이 막힘", "눈물이 났다", "무기력하다", "한숨이 났다", "피로감", "모르겠다"
]

ACTION_RECORDS = [
    "아무 반응 없음", "그 자리를 피했음", "화내며 대응", "조용히 참고 견딤", "울거나 감정 표현", 
    "다른 사람에게 하소연", "AI와 대화함", "혼자만의 시간을 가짐", "술이나 음식으로 달램", "운동이나 활동으로 해소"
]

DB_FILE = "mind_diary.db"

# --- SECTION 2: Backend Logic ---

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (date TEXT PRIMARY KEY, diary_content TEXT, analysis_json TEXT)''')
    conn.commit()
    conn.close()

def migrate_db_dates():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("SELECT date FROM logs")
        rows = c.fetchall()
        for r in rows:
            old_date = r[0]
            try:
                dt = datetime.strptime(old_date, "%Y-%m-%d")
                new_date = dt.strftime("%Y-%m-%d")
                if old_date != new_date:
                    c.execute("UPDATE logs SET date=? WHERE date=?", (new_date, old_date))
            except:
                pass
        conn.commit()
    except:
        pass
    conn.close()

def get_log(date_str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT diary_content, analysis_json FROM logs WHERE date=?", (date_str,))
    result = c.fetchone()
    conn.close()
    return result

def save_log(date_str, content, analysis_json):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO logs (date, diary_content, analysis_json) VALUES (?, ?, ?)",
              (date_str, content, analysis_json))
    conn.commit()
    conn.close()

def delete_log(date_str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM logs WHERE date=?", (date_str,))
    conn.commit()
    conn.close()

def get_all_dates_with_logs():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT date FROM logs")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_all_logs_for_calendar():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT date, analysis_json FROM logs")
    rows = c.fetchall()
    conn.close()
    return rows

def calculate_daily_score(analysis_json_str):
    try:
        data = json.loads(analysis_json_str)
        board = data.get("mindfulness_board", [])
        if not board: return 0
        total = sum([int(item.get("score", 0)) for item in board])
        return round(total / len(board))
    except:
        return 0

def get_prioritized_models(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url)
        if response.status_code != 200: return ["gemini-1.5-flash", "gemini-1.5-pro"]
        data = response.json()
        models = [m.get('name', '').replace('models/', '') for m in data.get('models', []) 
                  if 'generateContent' in m.get('supportedGenerationMethods', [])]
        flash = [m for m in models if 'flash' in m.lower()]
        pro = [m for m in models if 'pro' in m.lower() and m not in flash]
        return flash + pro + [m for m in models if m not in flash + pro]
    except:
        return ["gemini-1.5-flash", "gemini-1.5-pro"]

# --- [수정된 분석 함수: 따뜻한 기준 & 온도 설정 반영] ---
def analyze_diary(api_key, diary_text):
    if not api_key: return None
    model_list = get_prioritized_models(api_key)
    
    physical_list_str = ", ".join(PHYSICAL_REACTIONS)
    action_list_str = ", ".join(ACTION_RECORDS)
    
    system_instruction = f"""
    당신은 사용자의 일기를 분석하여 심리적 안정을 돕는 다정한 '마음 파트너'입니다. 
    이름은 '몽글곰팅 님'이며, 현재 '불안 창고'에 있는 무거운 감정들을 꺼내어 치유하는 중입니다.

    [채점 및 분석 특별 규칙]
    1. 따뜻한 가점 기준: 사용자가 완벽하지 않더라도 기록을 남기려 노력한 점을 높게 평가하여 '실행' 점수에 가산점을 주십시오.
    2. 일관성 유지: 과거 데스크탑 데이터 기준에 맞춰 긍정적인 변화를 독려하는 톤을 유지하세요.
    3. 반드시 다음 JSON 형식으로만 응답하시오.

    JSON 포맷:
    {{
        "mindfulness_board": [
            {{ "item": "감정", "character": "몽글이", "score": 3, "comment": "코멘트" }},
            {{ "item": "활동", "character": "꼼지", "score": 3, "comment": "코멘트" }},
            {{ "item": "신체", "character": "콩알이", "score": 3, "comment": "코멘트" }},
            {{ "item": "리듬", "character": "깜빡이", "score": 3, "comment": "코멘트" }},
            {{ "item": "실행", "character": "반짝이", "score": 3, "comment": "코멘트" }},
            {{ "item": "감사", "character": "성냥", "score": 3, "comment": "코멘트" }}
        ],
        "gratitude_note": ["감사1", "감사2", "감사3"],
        "partner_comment": {{ "title": "소제목", "content": "응원 메시지" }},
        "cbt_analysis": {{
            "part1_main_emotions": ["우울"], "part1_sub_emotions": ["슬픔"], "part1_intensity": 50,
            "part2_situation": "상황", "part3_thought": "생각", "part4_physical": ["두통"],
            "part5_action": ["AI와 대화함"], "part6_alternative": "대안"
        }}
    }}
    """
    
    prompt_text = f"{system_instruction}\n\n[사용자 일기]\n{diary_text}"
    
    for model_name in model_list:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        # 채점 기준 고정 (Temperature 0.1)
        payload = {{
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {{ "temperature": 0.1, "topP": 0.8, "maxOutputTokens": 2048 }}
        }}
        try:
            res = requests.post(url, headers={{"Content-Type": "application/json"}}, json=payload)
            if res.status_code == 200:
                text = res.json()['candidates'][0]['content']['parts'][0]['text']
                if "```json" in text: text = text.split("```json")[1].split("```")[0]
                elif "```" in text: text = text.split("```")[1].split("```")[0]
                return json.loads(text.strip())
        except: continue
    return None

def generate_monthly_insight(api_key, month_data_text):
    if not api_key: return "API 키가 필요합니다."
    model_list = get_prioritized_models(api_key)
    system_instruction = "당신은 몽글곰팅 님의 따뜻한 성장 파트너입니다. 한 달간의 데이터를 분석해 다정한 리포트를 작성하세요."
    prompt_text = f"{system_instruction}\n\n[데이터]\n{month_data_text}"
    for model_name in model_list:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            res = requests.post(url, headers={"Content-Type": "application/json"}, 
                                json={"contents": [{"parts": [{"text": prompt_text}]}]})
            if res.status_code == 200:
                return res.json()['candidates'][0]['content']['parts'][0]['text']
        except: continue
    return "분석 생성 실패"

# --- SECTION 3: UI Layout ---

st.set_page_config(layout="wide", page_title="마음챙김 & CBT 다이어리")
init_db()
migrate_db_dates()

with st.sidebar:
    st.title("설정")
    api_key = st.text_input("Google API Key", type="password")
    st.divider()
    if st.button("🔄 모든 데이터 재분석", type="primary"):
        st.info("재분석 중... 잠시만 기다려주세요.")
        # (생략: 기존 재분석 로직과 동일)

tab1, tab2 = st.tabs(["📝 오늘의 일기", "📊 월간 리포트"])

with tab1:
    if "selected_date_str" not in st.session_state:
        st.session_state["selected_date_str"] = datetime.now().strftime("%Y-%m-%d")
    
    date_str = st.session_state["selected_date_str"]
    st.subheader(f"📅 {date_str}의 기록")
    
    saved_data = get_log(date_str)
    diary_input = st.text_area("오늘의 이야기를 들려주세요.", value=saved_data[0] if saved_data else "")
    
    if st.button("AI 분석 및 저장"):
        with st.spinner("분석 중..."):
            result = analyze_diary(api_key, diary_input)
            if result:
                save_log(date_str, diary_input, json.dumps(result, ensure_ascii=False))
                st.success("저장되었습니다!")
                st.rerun()

with tab2:
    st.header("📊 월간 마음 성장 리포트")
    # (생략: 리포트 시각화 로직)
    st.info("일기 데이터가 쌓이면 여기서 월간 리포트를 확인할 수 있습니다.")
