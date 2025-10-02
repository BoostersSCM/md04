import streamlit as st
import pandas as pd
from datetime import datetime

# ----------------------------------------------------------------------
# 1. 페이지 설정 및 DB 연동 함수
# ----------------------------------------------------------------------

# --- 페이지 기본 설정 ---
st.set_page_config(page_title="고급 재고 관리 시스템", layout="wide")

# --- 제목 ---
st.title("📦 고급 재고 관리 시스템 (w/ 안전재고)")
st.write("안전재고를 설정하고, 사용 가능 재고를 실시간으로 추적합니다.")

# --- DB 연동 ---
# st.connection을 사용하면 Streamlit Cloud의 Secrets 정보를 자동으로 읽어옵니다.
conn = st.connection("mysql", type="sql")

# --- DB 업데이트 함수 (실제 DB에 안전재고를 업데이트) ---
def update_safety_stock_in_db(item_code, safety_stock):
    """선택한 품번의 안전재고 수량을 DB에 업데이트합니다."""
    # with conn.session as s: 를 사용하면 SQL Injection을 방지하며 안전하게 쿼리 실행 가능
    with conn.session as s:
        # 아래 UPDATE 쿼리는 실제 테이블과 컬럼명에 맞게 수정해야 합니다.
        s.execute(
            'UPDATE 제품마스터 SET 안전재고 = :stock WHERE 품번 = :code;',
            params=dict(stock=safety_stock, code=item_code)
        )
        s.commit()

# --- 데이터 로드 함수 (캐싱 적용) ---
@st.cache_data(ttl=300) # 5분 동안 캐시 유지
def load_data_from_db():
    # 품번/품명/안전재고 마스터 데이터 로드
    item_master_query = "SELECT 품번, 품명, 안전재고 FROM 제품마스터;"
    item_master_df = conn.query(item_master_query, ttl=300)
    
    # 재고 입출고 데이터 로드
    inventory_query = "SELECT 품번, 일자, 내역, `입고 수량`, `출고 수량` FROM 재고내역;"
    inventory_df = conn.query(inventory_query, ttl=300)
    
    if not inventory_df.empty:
        inventory_df['일자'] = pd.to_datetime(inventory_df['일자'])
        
    return item_master_df, inventory_df

# --- 데이터 로드 및 세션 상태 초기화 ---
try:
    # 앱이 처음 실행될 때만 DB에서 데이터를 로드하여 세션 상태에 저장
    if 'master_data' not in st.session_state:
        master_df, inventory_df = load_data_from_db()
        # DataFrame을 '품번'을 key로 하는 딕셔너리로 변환하여 관리 (조회 및 업데이트 용이)
        st.session_state.master_data = master_df.set_index('품번').to_dict('index')
        st.session_state.inventory_data = inventory_df
    
    master_data_dict = st.session_state.master_data
    inventory_df = st.session_state.inventory_data

# ----------------------------------------------------------------------
# 2. 사이드바 (안전재고 설정)
# ----------------------------------------------------------------------

    with st.sidebar:
        st.header("⚙️ 안전재고 설정")
        
        # 설정할 품번 선택
        item_list_for_setting = list(master_data_dict.keys())
        selected_item = st.selectbox("품번 선택", options=item_list_for_setting)
        
        if selected_item:
            current_safety_stock = master_data_dict[selected_item]['안전재고']
            
            # 안전재고 입력 필드
            new_safety_stock = st.number_input(
                f"'{master_data_dict[selected_item]['품명']}'의 안전재고 설정",
                min_value=0,
                value=current_safety_stock,
                step=10,
                key=f"ss_{selected_item}" # 각 품목별로 고유한 위젯 키 부여
            )
            
            # 저장 버튼
            if st.button("안전재고 저장"):
                try:
                    # 1. DB에 업데이트
                    update_safety_stock_in_db(selected_item, new_safety_stock)
                    
                    # 2. 세션 상태(화면)에 즉시 반영
                    st.session_state.master_data[selected_item]['안전재고'] = new_safety_stock
                    
                    # 3. 캐시 클리어하여 다음번 실행 시 DB에서 새로운 값 로드
                    st.cache_data.clear()
                    st.success(f"'{selected_item}'의 안전재고가 {new_safety_stock}으로 저장되었습니다.")
                except Exception as e:
                    st.error(f"DB 업데이트 중 오류 발생: {e}")

# ----------------------------------------------------------------------
# 3. 메인 화면 UI 구성
# ----------------------------------------------------------------------
    
    # --- 품번 선택 위젯 (메인 화면) ---
    available_items = list(master_data_dict.keys())
    options = ['선택하세요'] + available_items
    item_code_input = st.selectbox("조회할 품번을 선택하세요:", options)

    # --- 결과 표시 로직 ---
    if item_code_input and item_code_input != '선택하세요':
        item_info = master_data_dict[item_code_input]
        item_name = item_info['품명']
        safety_stock = item_info['안전재고']

        st.markdown("---")

        # 해당 품번의 재고 내역 필터링 및 정렬
        item_transactions = inventory_df[inventory_df['품번'] == item_code_input].copy()
        item_transactions = item_transactions.sort_values(by='일자', ascending=True)

        # 현재고 계산
        current_stock = 0
        if not item_transactions.empty:
            current_stock = (item_transactions['입고 수량'].sum() - item_transactions['출고 수량'].sum())
        
        # 사용 가능 재고 계산
        available_stock = current_stock - safety_stock

        # --- 재고 현황 요약 (Metric 사용) ---
        st.subheader(f"📊 '{item_name}' 재고 현황 요약")
        col1, col2, col3 = st.columns(3)
        col1.metric("현재고", f"{int(current_stock)} 개")
        col2.metric("안전재고", f"{int(safety_stock)} 개")
        col3.metric("사용 가능 재고", f"{int(available_stock)} 개")
        
        # 사용 가능 재고가 0 이하일 경우 경고 메시지 표시
        if available_stock <= 0:
            st.error(f"🚨 경고: 사용 가능 재고가 부족합니다! (현재고: {int(current_stock)}, 안전재고: {int(safety_stock)})")
        
        st.markdown("---")

        # --- 재고 상세 내역 테이블 ---
        if not item_transactions.empty:
            item_transactions['잔량'] = (item_transactions['입고 수량'] - item_transactions['출고 수량']).cumsum()
            st.subheader("📋 재고 입출고 상세 내역")
            display_df = item_transactions[['일자', '내역', '입고 수량', '출고 수량', '잔량']].reset_index(drop=True)
            display_df['일자'] = display_df['일자'].dt.strftime('%Y-%m-%d')
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.warning("해당 품번에 대한 재고 내역이 없습니다.")

    else:
        st.info("위에서 조회할 품번을 선택해주세요.")

except Exception as e:
    st.error(f"데이터베이스 연결 또는 데이터 로드 중 오류가 발생했습니다: {e}")
    st.info("Streamlit Cloud 설정에서 Secrets 정보가 올바르게 입력되었는지 확인하세요.")
