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
    
    # 1. Get List of Candidates
    model_list = get_prioritized_models(api_key)
    
    # Fallback list if API fails entirely
    if not model_list:
        model_list = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]
        
    print(f"Attempting models in order: {model_list}")
    
    # Lists for Prompt
    physical_list_str = ", ".join(PHYSICAL_REACTIONS)
    action_list_str = ", ".join(ACTION_RECORDS)
    
    system_instruction = f"""
    당신은 사용자의 일기를 분석하여 심리적 안정을 돕는 전문적이고 다정한 '프로 코치'입니다.
    (톤앤매너: 공감 20%, 객관적 진단 50%, 현실적 전략 30% - 냉철하지만 따뜻하게)
    사용자의 이름은 '몽글곰팅 님'입니다.
    사용자가 일기(텍스트)를 입력하면, 반드시 다음 JSON 형식으로 결과를 반환해야 합니다.

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
        "gratitude_note": [
            "비록 오류가 많았지만, 끝까지 해결책을 찾으려 노력한 나의 열정에 감사합니다.",
            "지친 몸을 뉘일 수 있는 따뜻한 집이 있음에 감사합니다.",
            "복잡한 마음을 글로 적으며 스스로를 위로할 수 있어 감사합니다."
        ],
        "partner_comment": {{
            "title": "15자 내외의 소제목",
            "content": "사용자의 감정을 읽어주고, 전문가로서 다정하게 조언하고 응원하는 메시지"
        }},
        "cbt_analysis": {{
            "part1_main_emotions": ["우울", "불안"],
            "part1_sub_emotions": ["외로움"],
            "part1_intensity": 50,
            "part2_situation": "객관적인 사실 위주 요약",
            "part3_thought": "상황에서 떠오른 즉각적인 생각이나 걱정",
            "part4_physical": ["심장 빨라짐"],
            "part5_action": ["혼자만의 시간을 가짐"],
            "part6_alternative": "사용자가 상황을 긍정적이거나 현실적으로 다시 바라볼 수 있도록 돕는 말"
        }}
    }}
    
    [작성 규칙 - 엄수]
    1. 마음 챙김 보드 (Mindfulness Board):
       - 6가지 항목(감정, 활동, 신체, 리듬, 실행, 감사) 필수 포함.
       - 점수는 1~5점 척도.
       - [코멘트]는 해당 점수를 준 이유를 따뜻하게 한 줄로 요약.
       - (중요) '실행(반짝이)' 항목은 두려움이나 어려움에도 불구하고 무언가를 시도했거나 실천했다면 고득점을 부여하세요.
       - (중요) '신체(콩알이)' 항목은 스트레스성 폭식, 과식, 수면 부족 등의 여부를 냉정히 반영하되 그 원인을 함께 분석하는 코멘트를 적어주세요.
    
    2. 오늘의 감사 노트:
       [작성 요령: 오늘의 감사 노트 (3가지 필수)]
       사용자가 직접적으로 '감사하다'고 말하지 않아도, 일기 내용을 깊이 분석하여 부정적인 상황 속에서도 긍정적인 측면(Silver Lining)을 찾아내어 작성하세요. 
       없는 사실을 지어내지 말고, 다음 관점에서 재해석하십시오.
       
       1. 관점의 전환: "실패했다" -> "배움의 기회를 얻어 감사합니다."
       2. 과정에 대한 인정: "힘들었다" -> "힘든 상황을 버텨낸 나의 인내심에 감사합니다."
       3. 소소한 배경: 일기에 언급된 '커피', '잠', '집', '가족' 등 배경 요소가 주는 편안함에 감사합니다.
       4. 기록의 가치: 힘든 하루를 보내고도 이 자리에 앉아 마음을 정리하려는 의지에 감사합니다.
    
       * 주의: 문장은 반드시 "~했습니다" 또는 "~감사합니다"로 끝맺으세요. 절대 빈칸 금지.
       
    3. 마음 파트너의 한마디:
       - 15자 내외의 [소제목]을 반드시 포함.
       - 따뜻하고 다정한 응원 및 코칭 메시지.
       
    4. CBT 감정 노트 (심층 분석):
       - **중요: 복수 선택 항목(감정, 신체, 행동)은 "하나만 고르지 말고, 관련된 건 모두" 선택할 것.**
       - [Part 1] 감정 선택지는 다음 목록에서만 선택 (복수 선택 강력 권장): 
         (주요): {", ".join(EMOTIONS_MAIN)}
         (기타): {", ".join(EMOTIONS_OTHER)}
       - [Part 4] 신체 반응 선택지는 다음 목록에서만 선택 (복수 선택 권장): [{physical_list_str}]
       - [Part 5] 행동 기록 선택지는 다음 목록에서만 선택 (복수 선택 권장): [{action_list_str}]
       - [Part 2, 3, 6]은 적절한 텍스트로 작성.
       - **중요: 'part6_alternative' 및 분석 내용 작성 시, 부정적 감정이나 행동 이면에 숨겨진 '긍정적 의도(예: 잘하고 싶은 마음, 성취욕구, 자신을 보호하려는 방어 기제 등)'도 함께 찾아내어 사용자가 자신을 탓하지 않고 더 유연하게 바라볼 수 있도록 작성하세요.**

    반드시 유효한 JSON 문자열만 반환하시오. 마크다운 코드블록 없이 순수 JSON만 반환.
    """
    
    prompt_text = f"{system_instruction}\n\n[사용자 일기]\n{diary_text}"
    
    last_error_msg = ""
    
    # 2. Iterate and Retry
    for model_name in model_list:
        print(f"Trying model: {model_name}...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt_text}]
            }],   
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                # Success!
                result = response.json()
                try:
                    text = result['candidates'][0]['content']['parts'][0]['text']
                    # Clean up JSON
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.startswith("```"):
                            text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    
                    try:
                        parsed_json = json.loads(text.strip())
                    except json.JSONDecodeError:
                        raise ValueError("Invalid JSON format")

                    # [Validation & Recovery]
                    # 1. Check Mindfulness Board
                    if "mindfulness_board" not in parsed_json or not isinstance(parsed_json["mindfulness_board"], list):
                        print(f"Warning ({model_name}): Missing mindfulness_board. Using defaults.")
                        parsed_json["mindfulness_board"] = [
                            {"item": "감정", "character": "몽글이", "score": 1, "comment": "분석 실패 (기본값)"},
                            {"item": "활동", "character": "꼼지", "score": 1, "comment": "분석 실패 (기본값)"},
                            {"item": "신체", "character": "콩알이", "score": 1, "comment": "분석 실패 (기본값)"},
                            {"item": "리듬", "character": "깜빡이", "score": 1, "comment": "분석 실패 (기본값)"},
                            {"item": "실행", "character": "반짝이", "score": 1, "comment": "분석 실패 (기본값)"},
                            {"item": "감사", "character": "성냥", "score": 1, "comment": "분석 실패 (기본값)"}
                        ]

                    # 2. Check Gratitude
                    if "gratitude_note" not in parsed_json:
                        if "gratitude_list" in parsed_json:
                             parsed_json["gratitude_note"] = parsed_json["gratitude_list"]
                        else:
                             parsed_json["gratitude_note"] = ["분석된 감사 내용이 없습니다."]
                        
                    return parsed_json

                except Exception as e:
                    print(f"Parse error ({model_name}): {e}")
                    last_error_msg = f"Model {model_name} Parse Error: {e}\nRaw Text: {text[:100]}..."
                    continue # Try next model
            else:
                # API Error
                print(f"API Failure ({model_name}): {response.status_code} - {response.text}")
                last_error_msg = f"Model {model_name} API Error ({response.status_code}): {response.text}"
                continue
                
        except Exception as e:
            print(f"Connection error ({model_name}): {e}")
            last_error_msg = f"Connection Error: {e}"
            continue

    # 3. If all failed
    st.error(f"분석 실패. 마지막 오류: {last_error_msg}")
    
    # [Debug] Show technical details
    with st.expander("에러 상세 정보 (개발자용)"):
        st.write("마지막 API 응답 혹은 에러:")
        st.code(last_error_msg)
        
    st.info("API 키를 확인하거나, 잠시 후 다시 시도해주세요.")
    return None

def generate_monthly_insight(api_key, month_data_text, user_name="몽글곰팅"):
    """
    Generates a deep insight report for the month based on diary and CBT data.
    """
    if not api_key:
        return "API Key가 설정되지 않았습니다."
        
    model_list = get_prioritized_models(api_key)
    if not model_list:
        model_list = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]
        
    system_instruction = f"""
    당신은 심리 상담 전문가이자 '{user_name} 님'의 따뜻한 마음 성장 파트너입니다.
    사용자의 한 달 치 일기와 CBT(인지행동치료) 분석 데이터를 바탕으로 **'AI 심층 회고 리포트'**를 작성해 주세요.
    정확한 사실 기반 통찰력을 주면서도, 다정하고 응원하는 어조를 유지하세요.

    [주의사항 및 핵심 규칙]
    - 사용자를 반드시 **'{user_name} 님'**이라고 호칭할 것. (예: "으뜸 님" 대신 "몽글곰팅 님")
    - 제공된 데이터 내에서만 추론하세요.
    - 비판하거나 가르치려 하지 말고, "발견했습니다", "제안해 봅니다" 등의 수용적인 표현을 사용하세요.
    """
    
    prompt_text = f"{system_instruction}\n\n[이번 달 기록 (일기 및 CBT 데이터 요약)]\n{month_data_text}"
    
    for model_name in model_list:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt_text}]
            }]
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()
                text = result['candidates'][0]['content']['parts'][0]['text']
                # Clean up if model still output markdown blocks
                if text.startswith("```markdown"):
                    text = text[11:]
                elif text.startswith("```"):
                     text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                return text.strip()
            else:
                continue
        except:
             continue
    
    return "💡 분석을 생성하지 못했습니다. 일시적인 서버 오류일 수 있으니 잠시 후 다시 시도해주세요."
    
# --- SECTION 3: UI Layout ---

st.set_page_config(layout="wide", page_title="마음챙김 & CBT 다이어리")

# Initialize DB
init_db()
migrate_db_dates()

# 1. Sidebar
with st.sidebar:
    st.title("설정")
    
    # Try to load from secrets
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("API Key가 자동으로 로드되었습니다.")
    else:
        api_key = st.text_input("Google API Key", type="password")
        st.caption("API Key가 입력되어야 메인 화면이 작동합니다.")
        
    st.divider()
    
    # 2. History List (Backup Navigation)
    with st.expander("📂 기록 목록 (백업)", expanded=False):
        st.caption("캘린더에서 날짜가 안 보이면 여기서 선택하세요.")
        history_dates = get_all_dates_with_logs()
        # Sort reverse chronological
        history_dates.sort(reverse=True)
        
        for d in history_dates:
            if st.button(f"📄 {d}", key=f"hist_{d}"):
                st.session_state["selected_date_str"] = d
                st.rerun()

    st.divider()

    # 3. Admin Tools (Reanalyze All)
    with st.expander("⚙️ 관리자 도구 (전체 재분석)", expanded=False):
        st.warning("⚠️ 모든 과거 데이터를 새로운 분석 기준으로 다시 분석합니다. 기존 데이터는 덮어씌워집니다. 시간이 다소 소요될 수 있습니다.")
        if st.button("🔄 모든 과거 데이터 재분석 실행", type="primary", use_container_width=True):
            if not api_key:
                st.error("설정에서 API Key를 먼저 입력해주세요.")
            else:
                # Backup DB First
                try:
                    if os.path.exists(DB_FILE):
                        backup_name = "mind_diary_backup.db"
                        shutil.copy(DB_FILE, backup_name)
                        st.success(f"✅ DB 백업 완료 ({backup_name})")
                except Exception as e:
                    st.error(f"❌ DB 백업 실패: {e}")
                    st.stop()
                    
                # Fetch all non-empty diaries
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("SELECT date, diary_content FROM logs WHERE diary_content IS NOT NULL AND diary_content != ''")
                all_entries = c.fetchall()
                
                if not all_entries:
                    st.info("재분석할 일기 데이터가 없습니다.")
                    conn.close()
                else:
                    st.info(f"총 {len(all_entries)}건의 데이터를 재분석합니다...")
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    success_count = 0
                    fail_count = 0
                    
                    for i, (d_str, content) in enumerate(all_entries):
                        status_text.text(f"분석 중... ({i+1}/{len(all_entries)}) : {d_str}")
                        
                        try:
                            # analyze
                            result_json = analyze_diary(api_key, content)
                            if result_json:
                                json_str = json.dumps(result_json, ensure_ascii=False)
                                # UPDATE with transaction per row for safety
                                c.execute("UPDATE logs SET analysis_json=? WHERE date=?", (json_str, d_str))
                                conn.commit()
                                success_count += 1
                            else:
                                fail_count += 1
                                
                            # Rate limit handling: Sleep between API calls
                            time.sleep(2)
                            
                        except Exception as e:
                            fail_count += 1
                            print(f"[Admin Reanalyze] Error on {d_str}: {e}")
                            
                        progress_bar.progress((i + 1) / len(all_entries))
                        
                    conn.close()
                    status_text.text(f"완료! 성공: {success_count}건, 실패: {fail_count}건")
                    
                    if fail_count == 0:
                        st.success("모든 기록이 새로운 기준으로 업데이트되었습니다!")
                    else:
                        st.warning(f"완료되었으나 {fail_count}건 실패했습니다. 나중에 다시 시도해 주세요.")
                        
                    time.sleep(2)
                    st.rerun()

# 2. Main Header
st.title("🧠 마음챙김 & CBT 다이어리")

# --- UI TABS ---
tab1, tab2 = st.tabs(["📝 오늘의 일기", "📊 월간 마음 성장 리포트"])

with tab1:
    if "selected_date_str" not in st.session_state:
        st.session_state["selected_date_str"] = datetime.now().strftime("%Y-%m-%d")

    # 캘린더 이벤트 및 스타일링 설정
    # 0. 감정 이모지 매핑
    EMOJI_MAP = {
        1: "😢", # 슬픔
        2: "😟", # 걱정/불안
        3: "😐", # 평온/보통
        4: "🙂", # 기쁨/만족
        5: "😄"  # 아주 좋음
    }

    # 1. 캘린더 이벤트 데이터 생성 (이모지 표시)
    calendar_events = []
    all_logs = get_all_logs_for_calendar()

    for row in all_logs:
        raw_date = row["date"]
        
        # Date Normalization (YYYY-MM-DD)
        try:
            dt = datetime.strptime(raw_date, "%Y-%m-%d")
            normalized_date = dt.strftime("%Y-%m-%d")
        except ValueError:
            try:
                 parts = raw_date.split('-')
                 if len(parts) == 3:
                     normalized_date = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                 else:
                     normalized_date = raw_date
            except:
                 normalized_date = raw_date
        
        json_str = row["analysis_json"]
        avg_score = calculate_daily_score(json_str)
        
        if avg_score > 0:
            emoji = EMOJI_MAP.get(avg_score, "😐")
            # 이모지 + 점수 (줄바꿈)
            display_title = f"{emoji}\n{avg_score}" 
            calendar_events.append({
                "title": display_title,
                "start": normalized_date,
                "allDay": True,
                "backgroundColor": "transparent",
                "borderColor": "transparent",
                "textColor": "#000000",
                "className": "emotion-emoji"
            })

    # 1. Custom CSS로 캘린더 크기 확대 및 스타일링
    custom_css = """
        .fc {
            font-size: 16px; /* 12px -> 16px 확대 */
            max-width: 600px; /* 400px -> 600px 확대 */
            margin: 0 auto;
        }
        .fc-header-toolbar {
            font-size: 14px;
            margin-bottom: 0.5em !important;
        }
        .fc-toolbar-title {
            font-size: 1.25em !important;
        }
        .fc-button {
            padding: 0.3em 0.5em !important;
            font-size: 1.0em !important;
            color: #000000 !important;
        }
        .fc-daygrid-day-frame {
            min-height: 85px !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
            padding-top: 4px !important;
        }
        
        .fc-daygrid-day-top {
            flex-direction: row !important;
            width: 100% !important;
            justify-content: center !important;
            margin-bottom: 2px !important;
        }
        /* 날짜 숫자 색상 강제 */
        .fc-daygrid-day-number {
            color: #333333 !important;
            text-decoration: none !important;
        }
        
        .fc-daygrid-day-events {
            margin: 0 !important;
            width: 100% !important;
            display: flex !important;
            justify-content: center !important;
        }
        
        /* 이모지 스타일링 - 크기 확대 */
        .fc-event-title {
            font-size: 1.2em !important; 
            text-align: center !important;
            display: block !important;
            width: 100% !important;
            white-space: pre !important;
            overflow: visible !important;
            line-height: 1.3 !important;
            color: #000000 !important;
            font-weight: bold !important;
        }
        
        .fc-event {
            box-shadow: none !important;
            background: transparent !important;
            border: none !important;
            position: static !important;
            pointer-events: none;
        }

        /* --- Global Text Container Fixes --- */
        /* Target all textareas (Today's Record, CBT Notes) */
        textarea {
            height: auto !important;
            min-height: 100px !important;
            field-sizing: content !important;
            white-space: pre-wrap !important;
            word-break: break-word !important;
            overflow-y: hidden !important; /* Hide vertical scrollbar */
            resize: none !important;      /* Hide manual resize handle */
        }

        /* Specifically for Gratitude Notes which have smaller min-height */
        [data-testid="stTextArea"] textarea[aria-label^="1."],
        [data-testid="stTextArea"] textarea[aria-label^="2."],
        [data-testid="stTextArea"] textarea[aria-label^="3."] {
            min-height: 68px !important;
        }

        /* Target Streamlit's info/success boxes (Partner's Message) */
        .stAlert {
            height: auto !important;
            white-space: pre-wrap !important;
            word-break: break-word !important;
        }
        
        /* Ensure st.markdown/st.write containers also wrap */
        .stMarkdown {
            white-space: pre-wrap !important;
            word-break: break-word !important;
        }
    """

    # 3. JavaScript for Auto-grow Textareas
    auto_grow_js = """
        <script>
        function autoGrowAll() {
            const textareas = window.parent.document.querySelectorAll('textarea');
            textareas.forEach(textarea => {
                if (!textarea.dataset.autogrow) {
                    textarea.dataset.autogrow = "true";
                    
                    // Initial height adjustment
                    textarea.style.height = 'auto';
                    textarea.style.height = textarea.scrollHeight + 'px';
                    
                    // Live adjustment on input
                    textarea.addEventListener('input', function() {
                        this.style.height = 'auto';
                        this.style.height = this.scrollHeight + 'px';
                    });
                } else {
                    // Update height if content changed externally (e.g. loading saved data)
                    textarea.style.height = 'auto';
                    textarea.style.height = textarea.scrollHeight + 'px';
                }
            });
        }

        // Run periodically and on interaction to catch Streamlit's reactive updates
        setInterval(autoGrowAll, 1000);
        window.parent.document.addEventListener('mouseover', autoGrowAll);
        window.parent.document.addEventListener('click', autoGrowAll);
        autoGrowAll();
        </script>
    """
    components.html(auto_grow_js, height=0)

    calendar_options = {
        "headerToolbar": {
            "left": "prev,next",
            "center": "title",
            "right": "today"
        },
        "initialDate": st.session_state["selected_date_str"],
        "selectable": True,
        "locale": "ko",
        "height": "auto",
        "contentHeight": "auto",
        "aspectRatio": 1.8
    }

    # 캘린더 렌더링 (Dropdown 스타일)
    with st.popover(f"📅 {st.session_state['selected_date_str']}"):
        cal_data = calendar(
            events=calendar_events, 
            options=calendar_options, 
            custom_css=custom_css, 
            callbacks=["dateClick"], 
            key=f"cal_{st.session_state['selected_date_str']}"
        )

        # 날짜 클릭 처리 (Popover 내부)
        if cal_data.get("dateClick"):
            clicked_date = cal_data["dateClick"]["date"]
            if clicked_date != st.session_state["selected_date_str"]:
                st.session_state["selected_date_str"] = clicked_date
                st.rerun()

    date_str = st.session_state["selected_date_str"]

    # Load existing data
    saved_data = get_log(date_str)
    existing_content = saved_data[0] if saved_data else ""
    existing_json_str = saved_data[1] if saved_data else "{}"

    try:
        analysis_data = json.loads(existing_json_str)
    except:
        analysis_data = {}

    # Layout
    col1, col2, col3 = st.columns([1.2, 1, 1])

    # Column 1: Input
    with col1:
        st.subheader("📝 오늘의 기록")
        diary_input = st.text_area("오늘 있었던 일을 자유롭게 적어주세요.", 
                                   value=existing_content if existing_content else "", 
                                   key=f"diary_input_{date_str}")
        
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("AI 분석 및 저장", type="primary"):
                if not api_key:
                    st.error("설정에서 API Key를 입력해주세요.")
                elif not diary_input:
                    st.warning("일기 내용을 입력해주세요.")
                else:
                    with st.spinner("AI가 일기를 분석 중입니다..."):
                        result_json = analyze_diary(api_key, diary_input)
                        if result_json:
                            # Update Session State directly to ensure UI reflects new data
                            new_gratitude = result_json.get("gratitude_note", [])
                            if not isinstance(new_gratitude, list):
                                new_gratitude = []
                                
                            # Handle exactly 3 items
                            for i in range(3):
                                key = f"g{i+1}_{date_str}"
                                val = ""
                                if i < len(new_gratitude):
                                    val = str(new_gratitude[i])
                                st.session_state[key] = val
                                
                            save_log(date_str, diary_input, json.dumps(result_json, ensure_ascii=False))
                            
                            # [Debug] Show what we just got
                            with st.expander("방금 분석된 데이터 확인 (디버그)", expanded=True):
                                st.json(result_json)
                                
                            st.success("저장 완료!")
                            
                            # Add a small delay/button to manually reload if needed, or just rerun
                            time.sleep(1) # Give it a moment (placebo but sometimes helps with DB sync)
                            st.rerun()
        with col_btn2:
            if st.button("🗑️ 초기화 (기록 삭제)"):
                delete_log(date_str)
                
                # Clear Session State to ensure UI resets immediately
                if f"diary_input_{date_str}" in st.session_state:
                    del st.session_state[f"diary_input_{date_str}"]
                for i in range(3):
                    g_key = f"g{i+1}_{date_str}"
                    if g_key in st.session_state:
                        del st.session_state[g_key]
                
                st.warning("오늘의 기록이 초기화되었습니다.")
                st.rerun()
                
        # Debug Info (Hidden by default)
        with st.expander("🛠️ 디버그 데이터 확인 (개발자용)"):
            st.json(analysis_data)
            st.write(f"Gratitude Raw: {analysis_data.get('gratitude_note', 'Not Found')}")

    # Default empty data structure for UI rendering
    default_mind_board = [
        {"item": "감정", "character": "몽글이", "score": 1, "comment": "-"},
        {"item": "활동", "character": "꼼지", "score": 1, "comment": "-"},
        {"item": "신체", "character": "콩알이", "score": 1, "comment": "-"},
        {"item": "리듬", "character": "깜빡이", "score": 1, "comment": "-"},
        {"item": "실행", "character": "반짝이", "score": 1, "comment": "-"},
        {"item": "감사", "character": "성냥", "score": 1, "comment": "-"}
    ]

    # Backward Compatibility & Extraction
    if "mindfulness_board" in analysis_data:
        current_board = analysis_data["mindfulness_board"]
        current_scores = { item['item']: item['score'] for item in current_board }
    else:
        # Fallback for old data or empty
        old_scores = analysis_data.get("scores", {"감정": 0, "활동": 0, "신체": 0, "리듬": 0, "실행": 0, "감사": 0})
        current_board = []
        for k, v in CHARACTERS.items():
            current_board.append({
                "item": k, 
                "character": v, 
                "score": old_scores.get(k, 0), 
                "comment": "기존 데이터"
            })
        current_scores = old_scores

    default_cbt = {
        "part1_main_emotions": [],
        "part1_sub_emotions": [],
        "part1_intensity": 50,
        "part2_situation": "",
        "part3_thought": "",
        "part4_physical": [],
        "part5_action": [],
        "part6_alternative": ""
    }
    current_cbt = analysis_data.get("cbt_analysis", default_cbt)

    # Column 2: Visualization
    with col2:
        st.subheader("📊 마음 챙김 보드")
        
        # Radar Chart
        categories = list(CHARACTERS.keys())
        values = [current_scores.get(c, 0) for c in categories]
        categories += [categories[0]]
        values += [values[0]]
        
        fig = go.Figure(data=go.Scatterpolar(
            r=values,
            theta=categories,
            fill='toself',
            name='Mindfulness Score'
        ))
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 5]
                )),
            showlegend=False,
            height=250,
            margin=dict(l=40, r=40, t=20, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Table Representation
        st.markdown("##### 📋 세부 분석 및 코멘트")
        # Using Pandas for cleaner table display
        df_board = pd.DataFrame(current_board)
        if not df_board.empty and "character" in df_board.columns:
            df_board = df_board[["item", "character", "score", "comment"]]
            df_board.columns = ["항목", "캐릭터", "점수", "코멘트"]
            st.table(df_board)
        else:
            st.info("데이터가 없습니다.")

        # Gratitude Note
        st.markdown("#### 🌷 오늘의 감사 노트")
        gratitude_list = analysis_data.get("gratitude_note", analysis_data.get("gratitude_list", []))
        gratitude_list = [g for g in gratitude_list if g.strip()]
        
        # Fallback if empty (Force generation of defaults if AI failed)
        if not gratitude_list:
            gratitude_list = ["AI가 감사 노트를 작성하지 못했습니다. 직접 적어보세요."]
            gratitude_list += [""] * 2
        
        if len(gratitude_list) < 3:
            gratitude_list += [""] * (3 - len(gratitude_list))
        elif len(gratitude_list) > 3:
            gratitude_list = gratitude_list[:3]
            
        g_inputs = []
        for i in range(3):
            key = f"g{i+1}_{date_str}"
            val = gratitude_list[i]
            
            if key not in st.session_state:
                st.session_state[key] = val
                
            g_inputs.append(st.text_area(f"{i+1}.", key=key, height=68))
        
        # Partner Comment
        st.markdown("#### 💌 마음 파트너의 한마디")
        partner = analysis_data.get("partner_comment", {"title": "대기 중...", "content": "일기를 작성하고 분석 버튼을 눌러보세요."})
        st.info(f"**[{partner.get('title', '무제')}]**\n\n{partner.get('content', '')}")

    # Column 3: CBT Notes
    with col3:
        st.subheader("❤️🩹 CBT 감정 노트")
        
        with st.form("cbt_form"):
            # Group 1: Parts 1, 2, 3
            with st.container():
                st.markdown("### 🧠 내면 탐색 (감정, 상황, 사고)")
                
                # Part 1
                st.markdown("**Part 1. 현재 감정**")
                
                default_main = current_cbt.get("part1_main_emotions", [])
                if not default_main and "part1_emotion" in current_cbt:
                     old_emo = current_cbt["part1_emotion"]
                     if old_emo in EMOTIONS_MAIN:
                         default_main = [old_emo]
                
                cbt_main_emotions = st.multiselect("주요 감정 (복수 선택)", EMOTIONS_MAIN, default=[x for x in default_main if x in EMOTIONS_MAIN])
                cbt_sub_emotions = st.multiselect("기타 감정 (복수 선택)", EMOTIONS_OTHER, default=[x for x in current_cbt.get("part1_sub_emotions", []) if x in EMOTIONS_OTHER])
                
                cbt_intensity = st.slider("감정의 강도 (%)", 0, 100, int(current_cbt.get("part1_intensity", 50)))
                
                st.markdown("---") # Divider
                
                # Part 2
                st.markdown("**Part 2. 상황 파악**")
                p2_text = current_cbt.get("part2_situation", "")
                cbt_situation = st.text_area("객관적 사실", value=p2_text)
                
                st.markdown("---") # Divider

                # Part 3
                st.markdown("**Part 3. 자동적 사고**")
                p3_text = current_cbt.get("part3_thought", "")
                cbt_thought = st.text_area("어떤 생각이 들었나요?", value=p3_text)
            
            st.markdown("<br>", unsafe_allow_html=True) # Spacer

            # Group 2: Parts 4, 5, 6
            with st.container():
                st.markdown("### 🏃 행동 및 변화 (신체, 행동, 대안)")
                
                # Part 4
                st.markdown("**Part 4. 신체 반응**")
                cbt_physical = st.multiselect("신체 반응 선택 (복수 선택)", PHYSICAL_REACTIONS, default=[x for x in current_cbt.get("part4_physical", []) if x in PHYSICAL_REACTIONS])
                
                # Part 5
                st.markdown("**Part 5. 행동 기록**")
                cbt_action = st.multiselect("행동 기록 선택 (복수 선택)", ACTION_RECORDS, default=[x for x in current_cbt.get("part5_action", []) if x in ACTION_RECORDS])
                
                st.markdown("---") # Divider

                # Part 6
                st.markdown("**Part 6. 대안적 관점**")
                p6_text = current_cbt.get("part6_alternative", "")
                cbt_alternative = st.text_area("긍정적/현실적 대안", value=p6_text)
            
            st.markdown("<br>", unsafe_allow_html=True) 

            if st.form_submit_button("수정사항 저장", type="primary"):
                updated_cbt = {
                    "part1_main_emotions": cbt_main_emotions,
                    "part1_sub_emotions": cbt_sub_emotions,
                    "part1_intensity": cbt_intensity,
                    "part2_situation": cbt_situation,
                    "part3_thought": cbt_thought,
                    "part4_physical": cbt_physical,
                    "part5_action": cbt_action,
                    "part6_alternative": cbt_alternative
                }
                analysis_data["cbt_analysis"] = updated_cbt
                
                analysis_data["gratitude_note"] = [g for g in g_inputs if g.strip()]
                
                save_log(date_str, diary_input, json.dumps(analysis_data, ensure_ascii=False))
                st.success("CBT 및 노트 내용이 저장되었습니다.")
                st.rerun()

# --- TAB 2: MONTHLY REPORT ---
with tab2:
    st.header("📊 월간 마음 성장 리포트")
    
    # helper for report data
    def get_report_data():
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM logs", conn)
        conn.close()
        return df

    df_logs = get_report_data()
    
    if df_logs.empty:
        st.info("데이터가 아직 없습니다. 일기를 작성해 보세요!")
    else:
        # Convert date to datetime and create Year-Month column
        df_logs['date_dt'] = pd.to_datetime(df_logs['date'])
        df_logs['year_month'] = df_logs['date_dt'].dt.strftime('%Y-%m')
        
        available_months = sorted(df_logs['year_month'].unique(), reverse=True)
        
        col_sel1, col_sel2 = st.columns([2, 1])
        with col_sel1:
            target_month = st.selectbox("분석할 월 선택", available_months, index=0)
        
        with col_sel2:
            # Print Button
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🖼️ 리포트 이미지로 저장", use_container_width=True):
                components.html(
                    """
                    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
                    <script>
                    setTimeout(() => {
                        const targetElement = window.parent.document.querySelector('.main');
                        if (targetElement) {
                            html2canvas(targetElement, {
                                scale: 2, // 고해상도 캡처
                                useCORS: true, // 외부 이미지 테인트 방지
                                backgroundColor: window.parent.document.body.style.backgroundColor || "#ffffff"
                            }).then(canvas => {
                                const link = document.createElement('a');
                                link.download = '월간_마음성장_리포트.png';
                                link.href = canvas.toDataURL('image/png');
                                link.click();
                            });
                        }
                    }, 500); // 렌더링 대기 시간
                    </script>
                    """,
                    height=0,
                )

        # Base month (previous month)
        target_idx = available_months.index(target_month)
        base_month = None
        if target_idx + 1 < len(available_months):
            base_month = available_months[target_idx + 1]
        
        # Data Extraction logic
        def parse_analysis(json_str):
            try:
                data = json.loads(json_str)
                # Mindfulness scores
                m_board = data.get("mindfulness_board", [])
                scores = {item['item']: item['score'] for item in m_board}
                
                # CBT 불안 강도
                cbt = data.get("cbt_analysis", {})
                anxiety = cbt.get("part1_intensity", 0)
                
                # Emotions
                emotions = cbt.get("part1_main_emotions", []) + cbt.get("part1_sub_emotions", [])
                
                return scores, anxiety, emotions
            except:
                return {}, 0, []

        parsed_data = df_logs['analysis_json'].apply(parse_analysis)
        df_logs['scores'] = parsed_data.apply(lambda x: x[0])
        df_logs['anxiety'] = parsed_data.apply(lambda x: x[1])
        df_logs['emotions'] = parsed_data.apply(lambda x: x[2])
        
        # Group by month and calculate averages/counts
        target_df = df_logs[df_logs['year_month'] == target_month]
        base_df = df_logs[df_logs['year_month'] == base_month] if base_month else pd.DataFrame()
        
        # 1. Metrics
        st.subheader("📌 핵심 지표 요약")
        m1, m2, m3, m4, m5 = st.columns(5)
        
        def get_avg_score(df, item):
            scores = [s.get(item, 0) for s in df['scores'] if item in s]
            return sum(scores) / len(scores) if scores else 0

        curr_days = len(target_df)
        curr_exec = get_avg_score(target_df, "실행")
        curr_gratitude = get_avg_score(target_df, "감사")
        curr_emotion = get_avg_score(target_df, "감정")
        curr_body = get_avg_score(target_df, "신체")
        curr_activity = get_avg_score(target_df, "활동")
        curr_rhythm = get_avg_score(target_df, "리듬")
        
        neg_keywords = ["우울", "불안", "무기력함", "짜증", "분노", "자책", "공포", "슬픔", "두려움", "절망감"]
        def count_neg_emotions(df):
            count = 0
            for emos in df['emotions']:
                if any(e in neg_keywords for e in emos):
                    count += 1
            return count
            
        curr_neg = count_neg_emotions(target_df)

        prev_days = len(base_df) if base_month else None
        prev_exec = get_avg_score(base_df, "실행") if base_month else None
        prev_gratitude = get_avg_score(base_df, "감사") if base_month else None
        prev_neg = count_neg_emotions(base_df) if base_month else None
        prev_emotion = get_avg_score(base_df, "감정") if base_month else None
        prev_body = get_avg_score(base_df, "신체") if base_month else None
        prev_activity = get_avg_score(base_df, "활동") if base_month else None
        prev_rhythm = get_avg_score(base_df, "리듬") if base_month else None

        # Handle cases where prev value might be identical (avoid redundant display) or 0
        def format_delta(curr, prev, unit=""):
            if prev is None:
                return None
            diff = curr - prev
            # Use specific formatting based on type
            if isinstance(diff, float):
                 return f"{diff:+.1f}{unit}"
            return f"{diff:+d}{unit}"

        m1.metric("총 기록 일수", f"{curr_days}일", delta=format_delta(curr_days, prev_days, "일") if base_month else None)
        m2.metric("평균 감정 점수", f"{curr_emotion:.1f}점", delta=format_delta(curr_emotion, prev_emotion) if base_month else None)
        m3.metric("평균 신체 점수", f"{curr_body:.1f}점", delta=format_delta(curr_body, prev_body) if base_month else None)
        m4.metric("평균 활동 점수", f"{curr_activity:.1f}점", delta=format_delta(curr_activity, prev_activity) if base_month else None)
        m5.metric("평균 리듬 점수", f"{curr_rhythm:.1f}점", delta=format_delta(curr_rhythm, prev_rhythm) if base_month else None)

        st.divider()

        # 2. Charts
        c_col1, c_col2 = st.columns(2)
        
        with c_col1:
            st.markdown("##### 1. 마음 밸런스 비교 (전월 대비)")
            categories = ["감정", "활동", "신체", "리듬", "실행", "감사"]
            curr_vals = [get_avg_score(target_df, c) for c in categories]
            
            fig_radar = go.Figure()
            if base_month:
                prev_vals = [get_avg_score(base_df, c) for c in categories]
                fig_radar.add_trace(go.Scatterpolar(
                    r=prev_vals + [prev_vals[0]],
                    theta=categories + [categories[0]],
                    name=f'지난달 ({base_month})',
                    line=dict(color='gray', dash='dash'),
                    fill=None
                ))
            
            fig_radar.add_trace(go.Scatterpolar(
                r=curr_vals + [curr_vals[0]],
                theta=categories + [categories[0]],
                name=f'이번 달 ({target_month})',
                fill='toself',
                line=dict(color='#636EFA')
            ))
            
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 5])),
                showlegend=True, height=350, margin=dict(l=40, r=40, t=40, b=40)
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        with c_col2:
            st.markdown("##### 2. 긍정 vs 부정 감정 점유율")
            
            # 1. 이번 달 (Target Month) 데이터
            curr_all_emos = [e for sublist in target_df['emotions'] for e in sublist]
            curr_neg_count = sum(1 for e in curr_all_emos if e in neg_keywords)
            
            curr_has_data = len(curr_all_emos) > 0
            curr_neg_pct = (curr_neg_count / len(curr_all_emos)) * 100 if curr_has_data else 0
            curr_pos_pct = 100 - curr_neg_pct if curr_has_data else 0

            # 2. 지난달 (Base Month) 데이터
            prev_has_data = False
            prev_neg_pct = 0
            prev_pos_pct = 0
            
            if base_month and not base_df.empty:
                prev_all_emos = [e for sublist in base_df['emotions'] for e in sublist]
                prev_neg_count = sum(1 for e in prev_all_emos if e in neg_keywords)
                prev_has_data = len(prev_all_emos) > 0
                if prev_has_data:
                    prev_neg_pct = (prev_neg_count / len(prev_all_emos)) * 100
                    prev_pos_pct = 100 - prev_neg_pct

            if curr_has_data:
                y_labels = []
                neg_x = []
                pos_x = []
                neg_colors = []
                pos_colors = []
                
                # 지난달 먼저 넣기 (autorange="reversed" 시 위쪽에 배치됨)
                if prev_has_data:
                    y_labels.append(f'지난달 ({base_month})')
                    neg_x.append(prev_neg_pct)
                    pos_x.append(prev_pos_pct)
                    neg_colors.append('rgba(239, 85, 59, 0.4)')  # 흐린 빨강
                    pos_colors.append('rgba(0, 204, 150, 0.4)')  # 흐린 초록
                
                # 이번 달 데이터
                y_labels.append(f'이번 달 ({target_month})')
                neg_x.append(curr_neg_pct)
                pos_x.append(curr_pos_pct)
                neg_colors.append('rgba(239, 85, 59, 1.0)')     # 선명한 빨강 (기존 색상)
                pos_colors.append('rgba(0, 204, 150, 1.0)')     # 선명한 초록 (기존 색상)
                
                fig_bar = go.Figure(data=[
                    go.Bar(
                        name='부정',
                        y=y_labels,
                        x=neg_x,
                        orientation='h',
                        marker=dict(color=neg_colors),
                        text=neg_x,
                        texttemplate='%{text:.1f}%',
                        textposition='auto',
                        insidetextfont=dict(color='white'),
                        outsidetextfont=dict(color='black')
                    ),
                    go.Bar(
                        name='긍정/중립',
                        y=y_labels,
                        x=pos_x,
                        orientation='h',
                        marker=dict(color=pos_colors),
                        text=pos_x,
                        texttemplate='%{text:.1f}%',
                        textposition='auto',
                        insidetextfont=dict(color='white'),
                        outsidetextfont=dict(color='black')
                    )
                ])
                
                fig_bar.update_layout(
                    barmode='stack',
                    height=250 if prev_has_data else 180,
                    margin=dict(l=20, r=20, t=20, b=20),
                    xaxis=dict(title='%', range=[0, 100], dtick=10),
                    yaxis=dict(autorange="reversed"), # 위에서부터 지난달 -> 이번달 순서
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("비교할 감정 데이터가 부족합니다.")

        st.markdown("##### 3. 실행력과 불안의 상관관계")
        target_df = target_df.sort_values('date')
        target_df['day'] = target_df['date_dt'].dt.day
        
        exec_scores = [s.get("실행", 0) for s in target_df['scores']]
        
        fig_dual = go.Figure()
        fig_dual.add_trace(go.Bar(
            x=target_df['day'], y=exec_scores, name='실행 점수',
            marker=dict(color='#FFD700'), yaxis='y'
        ))
        fig_dual.add_trace(go.Scatter(
            x=target_df['day'], y=target_df['anxiety'], name='불안 강도',
            line=dict(color='#FF4B4B', width=3), yaxis='y2'
        ))
        
        fig_dual.update_layout(
            title=f"{target_month} 데일리 패턴",
            xaxis=dict(title='날짜 (일)', dtick=1),
            yaxis=dict(title='실행 점수 (1-5)', range=[0, 5.5], side='left'),
            yaxis2=dict(title='불안 강도 (0-100)', range=[0, 110], overlaying='y', side='right'),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            height=400, margin=dict(l=20, r=20, t=80, b=20)
        )
        st.plotly_chart(fig_dual, use_container_width=True)

        # 3. Rule-based Insights
        st.subheader("💡 마음 성장 코멘트")
        insights = []
        if curr_exec >= 4.0:
            insights.append("🚀 이번 달은 실행력이 매우 뛰어납니다! 꾸준한 실천이 성장의 밑거름이 되고 있어요.")
        elif base_month and prev_exec is not None and (curr_exec - prev_exec >= 1.0):
            insights.append("📈 지난달보다 실행력이 폭발적으로 성장했습니다! 자신감을 가지셔도 좋아요.")
            
        if curr_gratitude >= 4.0:
            insights.append("🌷 감사의 마음이 가득한 한 달이었네요. 긍정적인 에너지가 주변까지 밝게 비추고 있습니다.")
            
        body_avg = get_avg_score(target_df, "신체")
        if body_avg < 3.0:
            insights.append("💪 몸과 마음의 에너지를 충전할 시간이 필요해요. 가벼운 산책이나 충분한 휴식을 권장합니다.")
            
        if base_month and prev_neg is not None and curr_neg > prev_neg:
            insights.append("🌧️ 이번 달은 조금 힘든 날이 많았네요. 자책하기보다 그런 자신을 따뜻하게 안아주는 시간을 가져보세요.")
        
        if not insights:
            insights.append("🌱 꾸준히 기록하는 습관 자체가 이미 큰 성장입니다. 오늘 하루도 고생 많으셨어요.")
            
        for insight in insights:
            st.info(insight)
            
        st.divider()

        # 4. AI Deep Insight Report
        st.subheader("🧠 이달의 AI 심층 회고 (Deep Insight)")
        
        # Prepare data for AI Insight
        insight_key = f"insight_{target_month}"
        
        # Button to generate insight
        if st.button("✨ 심층 분석 생성하기", type="primary", use_container_width=True):
            if not api_key:
                st.error("설정에서 API Key를 입력해주세요.")
            else:
                with st.spinner("AI가 이번 달의 심리 패턴과 인사이트를 분석 중입니다... (약 10~20초 소요)"):
                    # Compile text data
                    compiled_text = f"[{target_month} 월간 기록]\n\n"
                    # Sort chronological
                    tdf = target_df.sort_values('date')
                    for _, row in tdf.iterrows():
                        d_str = row['date']
                        content = row['diary_content']
                        c_str = ""
                        try:
                           aj = json.loads(row['analysis_json'])
                           cbt = aj.get("cbt_analysis", {})
                           if cbt:
                                emo = ", ".join(cbt.get("part1_main_emotions", []) + cbt.get("part1_sub_emotions", []))
                                sit = cbt.get("part2_situation", "")
                                thgt = cbt.get("part3_thought", "")
                                act = ", ".join(cbt.get("part5_action", []))
                                alt = cbt.get("part6_alternative", "")
                                
                                c_str = f"- 주요감정: {emo}\n- 상황: {sit}\n- 생각: {thgt}\n- 행동: {act}\n- 대안: {alt}"
                        except:
                            pass
                            
                        compiled_text += f"---\n[{d_str}]\n일기: {content}\n[CBT 분석]\n{c_str}\n\n"
                        
                    # Call API
                    insight_text = generate_monthly_insight(api_key, compiled_text)
                    st.session_state[insight_key] = insight_text
                    
        # Display Insight View
        if insight_key in st.session_state:
            st.markdown(st.session_state[insight_key])
        else:
            st.info("버튼을 눌러 AI 심층 회고 리포트를 생성해 보세요. (한 달 치의 일기와 CBT 기록을 종합 분석합니다.)")



