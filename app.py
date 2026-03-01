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

# 1. 감정 캐릭터 및 항목
CHARACTERS = {
    "감정": "몽글이",
    "활동": "꼼지",
    "신체": "콩알이",
    "리듬": "깜빡이",
    "실행": "반짝이",
    "감사": "성냥"
}

# 2. 감정 선택지
EMOTIONS_MAIN = ["우울", "불안", "무기력함", "긴장감", "짜증", "분노", "자책", "공포"]
EMOTIONS_OTHER = ["기쁨", "슬픔", "두려움", "평온", "초조", "죄책감", "부끄러움", "외로움", "혼란", "절망감", "안도감", "만족감", "질투"]
ALL_EMOTIONS = EMOTIONS_MAIN + EMOTIONS_OTHER

# 3. 신체 반응 선택지
PHYSICAL_REACTIONS = [
    "심장 빨라짐", "손에 땀이 남", "근육 긴장", "답답함", "떨림", "두통", "소화불량", 
    "어지러움", "숨이 막힘", "눈물이 났다", "무기력하다", "한숨이 났다", "피로감", "모르겠다"
]

# 4. 행동 기록 선택지
ACTION_RECORDS = [
    "아무 반응 없음", "그 자리를 피했음", "화내며 대응", "조용히 참고 견딤", "울거나 감정 표현", 
    "다른 사람에게 하소연", "AI와 대화함", "혼자만의 시간을 가짐", "술이나 음식으로 달램", "운동이나 활동으로 해소"
]

# --- SECTION 2: Backend Logic ---

# 1. Database (SQLite)
DB_FILE = "mind_diary.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (date TEXT PRIMARY KEY, diary_content TEXT, analysis_json TEXT)''')
    conn.commit()
    conn.close()

def migrate_db_dates():
    """
    Migrates all dates in DB to YYYY-MM-DD format.
    Run this once to fix legacy data.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    try:
        c.execute("SELECT date FROM logs")
        rows = c.fetchall()
        
        migrated_count = 0
        from datetime import timedelta
        
        for r in rows:
            old_date = r[0]
            new_date = old_date
            
            try:
                # 1. Try ISO YYYY-MM-DD
                dt = datetime.strptime(old_date, "%Y-%m-%d")
                new_date = dt.strftime("%Y-%m-%d")
            except ValueError:
                try:
                    # 2. Try ISO 8601 with Z (e.g. 2026-01-26T15:00:00.000Z)
                    # Simple parse assuming Z is UTC
                    if 'T' in old_date and old_date.endswith('Z'):
                         base_str = old_date.split('.')[0] # 2026-01-26T15:00:00
                         dt = datetime.strptime(base_str, "%Y-%m-%dT%H:%M:%S")
                         # Add 9 hours for KST
                         dt_kst = dt + timedelta(hours=9)
                         new_date = dt_kst.strftime("%Y-%m-%d")
                    
                    # 3. Try YYYY-M-D
                    elif '-' in old_date:
                        parts = old_date.split('-')
                        if len(parts) == 3:
                            new_date = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                            datetime.strptime(new_date, "%Y-%m-%d") # Validate
                except:
                    pass
            
            # If format mismatch, update it
            if old_date != new_date:
                # Check if target already exists (collision)
                c.execute("SELECT 1 FROM logs WHERE date=?", (new_date,))
                if c.fetchone():
                    print(f"Skipping migration for {old_date} -> {new_date} (Target exists)")
                else:
                    c.execute("UPDATE logs SET date=? WHERE date=?", (new_date, old_date))
                    migrated_count += 1
                    
        if migrated_count > 0:
            print(f"Migrated {migrated_count} records to standard format.")
            conn.commit()
            
    except Exception as e:
        print(f"Migration failed: {e}")
        
    conn.close()

def normalize_date_str(date_str):
    try:
        # 1. Parse whatever is given
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        
        # 2. Return Standard (YYYY-MM-DD) AND Legacy (YYYY-M-D)
        std = dt.strftime("%Y-%m-%d")
        legacy = f"{dt.year}-{dt.month}-{dt.day}"
        return std, legacy
    except:
        # Fallback for ISO format reading
        if 'T' in date_str and date_str.endswith('Z'):
             try:
                 from datetime import timedelta
                 base_str = date_str.split('.')[0]
                 dt = datetime.strptime(base_str, "%Y-%m-%dT%H:%M:%S")
                 dt_kst = dt + timedelta(hours=9)
                 std = dt_kst.strftime("%Y-%m-%d")
                 return std, date_str # Return new std, but keep original as legacy key
             except:
                 pass
        return date_str, date_str

def get_log(date_str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Normalize date to standard format (YYYY-MM-DD) before querying
    final_date, _ = normalize_date_str(date_str)
    
    c.execute("SELECT diary_content, analysis_json FROM logs WHERE date=?", (final_date,))
    result = c.fetchone()
            
    conn.close()
    return result

def save_log(date_str, content, analysis_json):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Always normalize to YYYY-MM-DD when saving
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        normalized = dt.strftime("%Y-%m-%d")
        legacy = f"{dt.year}-{dt.month}-{dt.day}"
        
        # Delete legacy if exists to avoid duplicates
        if normalized != legacy:
            c.execute("DELETE FROM logs WHERE date=?", (legacy,))
            
        final_date = normalized
    except:
        final_date = date_str
        
    c.execute("INSERT OR REPLACE INTO logs (date, diary_content, analysis_json) VALUES (?, ?, ?)",
              (final_date, content, analysis_json))
    conn.commit()
    conn.close()

def delete_log(date_str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Try deleting BOTH standard and legacy to be sure
    std, legacy = normalize_date_str(date_str)
    
    c.execute("DELETE FROM logs WHERE date=?", (std,))
    c.execute("DELETE FROM logs WHERE date=?", (legacy,))
    
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
        if not board:
            return 0
        
        total_score = 0
        count = 0
        for item in board:
            try:
                score = int(item.get("score", 0))
                total_score += score
                count += 1
            except:
                continue
                
        if count == 0:
            return 0
            
        return round(total_score / count)
    except:
        return 0

from streamlit_calendar import calendar

# 2. Gemini API Logic (Direct REST API Version)
def get_prioritized_models(api_key):
    """
    Fetches available models and returns a prioritized list (Flash > Pro > Others).
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"List Models Failed: {response.text}")
            return []
        
        data = response.json()
        models = data.get('models', [])
        
        candidates = []
        for m in models:
            if 'generateContent' in m.get('supportedGenerationMethods', []):
                # Clean name: "models/gemini-pro" -> "gemini-pro"
                name = m.get('name', '').replace('models/', '')
                candidates.append(name)
        
        if not candidates:
            return []
            
        print(f"Available Models: {candidates}")
        
        # Smart Sort: Flash -> Pro -> Others
        sorted_candidates = []
        # 1. Flash (Fastest, usually free tier friendly)
        sorted_candidates.extend([c for c in candidates if 'flash' in c.lower()])
        # 2. Pro (Stable)
        sorted_candidates.extend([c for c in candidates if 'pro' in c.lower() and c not in sorted_candidates])
        # 3. Rest
        sorted_candidates.extend([c for c in candidates if c not in sorted_candidates])
        
        return sorted_candidates
        
    except Exception as e:
        print(f"Error listing models: {e}")
        return []

def analyze_diary(api_key, diary_text):
    if not api_key:
        return None
    
    # 1. 모델 리스트 가져오기
    model_list = get_prioritized_models(api_key)
    if not model_list:
        model_list = ["gemini-1.5-flash", "gemini-1.5-pro"]
        
    physical_list_str = ", ".join(PHYSICAL_REACTIONS)
    action_list_str = ", ".join(ACTION_RECORDS)
    
    # [프롬프트 수정] 몽글곰팅 님을 위한 따뜻한 가점 기준 추가
    system_instruction = f"""
    당신은 사용자의 일기를 분석하여 심리적 안정을 돕는 전문적이고 다정한 '프로 코치'입니다.
    (톤앤매너: 공감 20%, 객관적 진단 50%, 현실적 전략 30% - 냉철하지만 따뜻하게)
    사용자의 이름은 '몽글곰팅 님'입니다.

    [점수 산정 및 분석 특별 규칙]
    1. 사용자가 완벽하지 않더라도 '기록을 남기려 노력한 점'과 '자신을 돌아보려는 의지'가 보인다면, 실행 점수와 활동 점수에 가산점을 주어 긍정적인 변화를 독려하세요.
    2. 과거 데이터와 비교했을 때 급격히 점수가 낮아지지 않도록, 사용자의 '성장 과정' 그 자체를 높게 평가하십시오.
    3. 반드시 다음 JSON 형식으로 결과를 반환해야 합니다.

    JSON 포맷 구조:
    {{
        "mindfulness_board": [
            {{ "item": "감정", "character": "몽글이", "score": 3, "comment": "한 줄 코멘트" }},
            {{ "item": "활동", "character": "꼼지", "score": 3, "comment": "한 줄 코멘트" }},
            {{ "item": "신체", "character": "콩알이", "score": 3, "comment": "한 줄 코멘트" }},
            {{ "item": "리듬", "character": "깜빡이", "score": 3, "comment": "한 줄 코멘트" }},
            {{ "item": "실행", "character": "반짝이", "score": 3, "comment": "한 줄 코멘트" }},
            {{ "item": "감사", "character": "성냥", "score": 3, "comment": "한 줄 코멘트" }}
        ],
        "gratitude_note": ["감사내용1", "감사내용2", "감사내용3"],
        "partner_comment": {{ "title": "소제목", "content": "응원 메시지" }},
        "cbt_analysis": {{ ... }}
    }}
    
    (이하 상세 규칙 생략... 반드시 유효한 JSON만 반환)
    """
    
    prompt_text = f"{system_instruction}\n\n[사용자 일기]\n{diary_text}"
    
    for model_name in model_list:
        url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){model_name}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        
        # [채점 기준 고정] temperature를 0.1로 설정하여 일관성 확보
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "temperature": 0.1,
                "topP": 0.8,
                "maxOutputTokens": 2048
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()
                text = result['candidates'][0]['content']['parts'][0]['text']
                # JSON 정제 및 파싱 로직 (기존과 동일)
                if text.startswith("```json"): text = text[7:]
                if text.endswith("```"): text = text[:-3]
                return json.loads(text.strip())
        except:
            continue
    return None


