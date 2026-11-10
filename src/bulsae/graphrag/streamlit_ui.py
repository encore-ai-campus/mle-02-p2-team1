"""Customer-facing Streamlit UI over the existing read-only GraphRAG flow."""
import json
import logging
import os
import re
import sqlite3
import time
from copy import deepcopy
from datetime import datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import streamlit as st
from bulsae.graphrag import report_basket

logger = logging.getLogger(__name__)

RELATIONS = {'WORKS_AT': '재직', 'PARTICIPATED_IN': '참여', 'ANNOUNCED_STRATEGY': '전략 발표',
             'PARTNERS_WITH': '협력', 'PARENT_OF': '모회사', 'SUPPLIES_TO': '공급',
             'COLLABORATES_ON': '공동 활동', 'HAS_FINANCIAL': '재무 정보', 'HAS_MEMBER': '계열 구성',
             'OWNS_BRAND': '브랜드 보유', 'OPERATES': '운영', 'AFFILIATED_WITH': '소속', 'OPERATES_IN':'사업 운영',
             'EXPANDS_INTO':'시장 진출', 'OPERATES_BRAND':'브랜드 운영', 'HAS_PRODUCT':'제품 보유',
             'FOCUSES_ON':'중점 사업', 'TARGETS_MARKET':'목표 시장', 'PRESENTED_AT':'발표 행사', 'RELATED_TO':'관련 행사'}
CSS = """
<style>
.block-container{max-width:980px;padding-top:3.5rem;padding-bottom:5rem}
h1{letter-spacing:-.055em;font-size:2.3rem!important;font-weight:650}h2{font-size:1.35rem!important}h3{font-size:1.12rem!important}
.hero-title{margin:0 0 .55rem;font-size:clamp(2.3rem,5vw,3.7rem);font-weight:650;letter-spacing:-.065em;line-height:1.2;color:#302a2c;animation:arrive .65s ease-out both}
.hero-subtitle{margin:0 0 2.4rem;font-size:1rem;color:#9b8d91;animation:arrive .65s .1s ease-out both}
.question-title{margin:0 0 1.1rem;font-size:clamp(1.6rem,3vw,2.4rem)!important;font-weight:650;line-height:1.4;letter-spacing:-.045em;word-break:keep-all;overflow-wrap:anywhere;color:#302a2c;flex:1;min-width:0}
.question-heading{display:flex;align-items:baseline;gap:18px}
.question-mark{display:inline-flex;align-items:center;justify-content:center;flex:0 0 48px;width:48px;height:48px;border-radius:16px;background:#f0e2e7;color:#a66e7c;font-size:1.75rem;font-weight:750;line-height:1}
.question-enter .question-title{transform-origin:left top;animation:question-rise .7s cubic-bezier(.16,1,.3,1) both}
.question-enter .question-mark{animation:question-mark .6s .12s cubic-bezier(.16,1,.3,1) both}
.revenue-label{font-size:.95rem;color:#67434e;margin-bottom:12px}
.revenue-amounts{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap}
.revenue-value{font-size:clamp(1.6rem,3vw,2.4rem);font-weight:700;letter-spacing:-.045em;line-height:1.4;color:#a66e7c;overflow-wrap:anywhere;min-width:0}
.revenue-korean{font-size:1rem;line-height:1.7;color:#946371;word-break:keep-all}
.st-key-dashboard_toolbar{margin-bottom:1.2rem}
.st-key-dashboard_toolbar button{font-size:.85rem;color:#946371}
.st-key-save_to_basket{position:fixed!important;right:28px!important;bottom:28px!important;z-index:999999!important;width:auto!important}
.st-key-save_to_basket button{background:#aa7182!important;border:0!important;color:#fff!important;border-radius:13px!important;min-height:46px!important;padding:.55rem 1.1rem!important;font-size:.9rem!important;font-weight:650!important;box-shadow:0 8px 24px rgba(84,45,60,.2)!important}
.st-key-save_to_basket button:hover{background:#915b6c!important;color:#fff!important}
.basket-toast{position:fixed;top:24px;left:50%;transform:translateX(-50%);z-index:1000001;background:rgba(27,23,25,.9);color:#fff;padding:13px 20px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.18);font-size:.9rem;font-weight:600;white-space:nowrap;pointer-events:none;animation:basket-toast 3.5s ease forwards}
@keyframes basket-toast{0%{opacity:0;transform:translate(-50%,-8px)}10%,80%{opacity:1;transform:translate(-50%,0)}100%{opacity:0;visibility:hidden;transform:translate(-50%,-8px)}}
@media(max-width:600px){.st-key-save_to_basket{right:16px!important;bottom:16px!important}}
.st-key-top_navigation{margin-bottom:2.4rem;gap:.5rem!important}
.st-key-top_navigation button{border:1px solid #eadce1!important;border-radius:999px!important;background:#fff!important;color:#76515e!important;font-weight:600!important;padding:.42rem .95rem!important;min-height:2.5rem!important;box-shadow:0 2px 8px rgba(101,62,76,.04)}
.st-key-top_navigation button:hover{border-color:#c997a6!important;color:#a15f76!important;background:#fbf3f6!important}
.st-key-nav_basket{position:fixed!important;top:6px!important;right:56px!important;z-index:1000000!important;width:44px!important;height:44px!important}
.st-key-nav_basket button{background:transparent!important;border:0!important;box-shadow:none!important;color:#986477!important;width:44px!important;height:44px!important;min-height:44px!important;padding:0!important;display:flex!important;align-items:center!important;justify-content:center!important}
.st-key-nav_basket button:hover{background:transparent!important;color:#754455!important}
.st-key-nav_basket button span[data-has-shortcut]{display:flex!important;align-items:center!important;justify-content:center!important;gap:0!important}
.st-key-nav_basket button span[data-has-shortcut] > span:first-child{width:28px!important;height:28px!important;display:flex!important;align-items:center!important;justify-content:center!important}
.st-key-nav_basket button span[data-testid="stIconMaterial"]{font-size:28px!important;width:28px!important;height:28px!important;font-variation-settings:'FILL' 1,'wght' 650,'GRAD' 0,'opsz' 24!important;line-height:1!important}
.st-key-nav_basket button span[data-has-shortcut] > span[style]{display:block!important;position:absolute!important;width:1px!important;height:1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important}
.st-key-nav_basket button p{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
.st-key-nav_question{position:fixed!important;top:6px!important;left:16px!important;z-index:1000000!important;width:44px!important;height:44px!important}
.st-key-nav_question button{background:transparent!important;border:0!important;box-shadow:none!important;color:#986477!important;width:44px!important;height:44px!important;min-height:44px!important;padding:0!important;display:flex!important;align-items:center!important;justify-content:center!important}
.st-key-nav_question button span[data-has-shortcut]{display:flex!important;align-items:center!important;justify-content:center!important;gap:0!important}
.st-key-nav_question button span[data-has-shortcut] > span:first-child{width:26px!important;height:26px!important;display:flex!important;align-items:center!important;justify-content:center!important}
.st-key-nav_question button span[data-testid="stIconMaterial"]{font-size:26px!important;width:26px!important;height:26px!important;line-height:1!important}
.st-key-nav_question button span[data-has-shortcut] > span[style]{display:block!important;position:absolute!important;width:1px!important;height:1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important}
.basket-hero{display:flex;align-items:center;gap:18px;margin:0 0 1.65rem}
.basket-hero-icon{width:60px;height:60px;flex:0 0 60px;display:grid;place-items:center;background:#f2e1e7;border:1px solid #ead3dc;border-radius:19px;color:#a26579}
.basket-hero-icon svg{width:30px;height:30px}
.basket-eyebrow{font-size:.7rem;letter-spacing:.16em;color:#a67684;font-weight:700;margin-bottom:5px}
.basket-title{font-size:clamp(1.75rem,4vw,2.3rem);line-height:1.2;letter-spacing:-.055em;font-weight:700;color:#382c30;margin:0}
.basket-description{font-size:1rem;color:#856c74;line-height:1.65;margin:0 0 1rem}
.basket-meta{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:.4rem .8rem;background:#f6edf0;color:#906c78;font-size:.76rem;font-weight:600}
.basket-empty{margin-top:2rem;min-height:300px;border:1px solid #eee0e5;border-radius:24px;background:linear-gradient(150deg,#fff,#fdf8fa);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:36px 24px}
.basket-empty-icon{width:82px;height:82px;display:grid;place-items:center;border-radius:27px;background:#f7e9ee;color:#b07789;margin-bottom:23px}
.basket-empty-icon svg{width:40px;height:40px}
.basket-empty-title{font-size:1.15rem;font-weight:700;letter-spacing:-.04em;color:#4d3b42;margin:0 0 9px}
.basket-empty-copy{font-size:.9rem;line-height:1.7;color:#9d8990;margin:0}
.basket-list-heading{display:flex;align-items:baseline;justify-content:space-between;margin:2rem 0 .85rem;color:#6c4b57;font-size:.84rem;font-weight:700}
.basket-list-heading span{font-weight:500;color:#ab909a}
div[class*="st-key-basket_card_"]{background:#fff;border:1px solid #eee0e5!important;border-radius:20px!important;padding:1.35rem 1.5rem!important;box-shadow:0 8px 25px rgba(99,62,76,.045)}
div[class*="st-key-basket_card_"] h3{color:#49353d!important;letter-spacing:-.035em}
div[class*="st-key-basket_card_"] p{color:#755f67;line-height:1.7}
div[class*="st-key-basket_remove_"] button{border:0!important;background:transparent!important;box-shadow:none!important;color:#a68d96!important;width:32px!important;height:32px!important;min-height:32px!important;padding:0!important;display:flex!important;align-items:center!important;justify-content:center!important}
div[class*="st-key-basket_remove_"] button:hover{color:#764b5b!important;background:#f8edf1!important;border-radius:8px!important}
div[class*="st-key-basket_remove_"] button span[data-has-shortcut]{display:flex!important;align-items:center!important;justify-content:center!important;gap:0!important}
div[class*="st-key-basket_remove_"] button span[data-has-shortcut] > span[style]{display:block!important;position:absolute!important;width:1px!important;height:1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important}
.st-key-download_basket_report button{border-radius:14px!important;min-height:3rem!important;font-weight:700!important}
@media(max-width:600px){.basket-hero{gap:14px}.basket-hero-icon{width:52px;height:52px;flex-basis:52px;border-radius:16px}.basket-empty{min-height:260px}.st-key-top_navigation{margin-bottom:1.8rem}}
.st-key-answer_dashboard{gap:1.25rem}
.st-key-event_count,[class*="st-key-event_row_"]{width:100%;background:#fff;border:1px solid #eee5e7;border-radius:22px;box-shadow:0 6px 24px rgba(72,42,50,.025);min-width:0}
.st-key-event_count{padding:1rem 1.5rem}
[class*="st-key-event_row_"]{padding:1.5rem 1.8rem}
[class*="st-key-company_profile_"],[class*="st-key-company_news_"]{width:100%;background:#fff;border:1px solid #eee5e7;border-radius:22px;padding:1.5rem 1.8rem;min-width:0}
.company-profile-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.5rem 2.25rem}
.company-profile-item{min-width:0}
.company-profile-item--wide{grid-column:span 2}
.company-profile-label{font-size:.86rem;color:#947f86;margin-bottom:.4rem}
.company-profile-value{font-size:1.08rem;line-height:1.55;font-weight:650;color:#634450;word-break:keep-all;overflow-wrap:anywhere}
@media(max-width:700px){.company-profile-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:1.2rem 1.5rem}}
@media(max-width:420px){.company-profile-grid{grid-template-columns:minmax(0,1fr)}.company-profile-item--wide{grid-column:span 1}}
.st-key-event_analysis h4{color:#67434e;font-size:1.08rem!important;line-height:1.6}
.st-key-event_analysis li{color:#51474a;line-height:1.9}
.st-key-financial_factors{padding:1rem 0}
.st-key-event_analysis,.st-key-financial_analysis_report{background:#f6eef0;border:1px solid #eee0e5;border-radius:22px;padding:1.6rem 1.8rem;width:100%;min-width:0}
.st-key-financial_factors h4,.st-key-financial_analysis_report h4{font-size:1.08rem!important;color:#67434e;line-height:1.6;margin-top:.8rem;font-weight:650}
.st-key-financial_factors ul,.st-key-financial_analysis_report ul{padding-left:1.4rem;margin-left:0}
.st-key-financial_factors li,.st-key-financial_analysis_report li{color:#51474a;line-height:1.9;margin:.4rem 0}
.st-key-answer_overview,[class*="st-key-answer_card_"],[class*="st-key-analysis_card_"],[class*="st-key-financial_card_"]{background:#fff;border:1px solid #eee5e7;border-radius:22px;padding:1.5rem;box-shadow:0 6px 24px rgba(72,42,50,.025);height:100%;min-width:0}
.st-key-answer_overview{background:#f6eef0;border-color:#f0e3e7;padding:1.6rem 1.8rem}
[class*="st-key-analysis_card_"]{background:#fcf8f9}
.st-key-answer_dashboard [data-testid="stHeadingWithActionElements"] h3{font-size:1.1rem!important;font-weight:650;line-height:1.5;color:#67434e;padding-top:0}
.st-key-answer_dashboard [data-testid="stMarkdownContainer"] p{font-size:1rem;line-height:1.85;color:#51474a;overflow-wrap:anywhere}
.st-key-answer_dashboard [data-testid="stMetricValue"]{font-size:clamp(1.1rem,2.1vw,1.6rem);font-weight:650;color:#a66e7c}
.st-key-answer_dashboard [data-testid="stMetricValue"]>div{white-space:normal;overflow-wrap:anywhere;text-overflow:clip}
.st-key-answer_dashboard [data-testid="stCaptionContainer"]{color:#9b8d91}
.st-key-answer_dashboard [data-testid="stHorizontalBlock"]{align-items:stretch}
.st-key-answer_dashboard [data-testid="stColumn"]>[data-testid="stVerticalBlock"]{height:100%}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:20px}
[data-testid="stMarkdownContainer"] p{line-height:1.9}
[data-testid="stExpander"]{background:#fff;border-radius:16px}
[data-testid="stForm"]{border:0!important;outline:none!important;background:#fff;border-radius:24px;padding:1.25rem 1.5rem;box-shadow:0 12px 44px rgba(72,42,50,.06);animation:arrive .7s .18s ease-out both}
[data-testid="stForm"]:focus-within{box-shadow:0 14px 48px rgba(166,110,124,.12)}
[data-testid="stTextAreaRootElement"],[data-testid="stTextArea"] [data-baseweb="textarea"]{background:transparent!important;border:0!important;outline:none!important;box-shadow:none!important}
[data-testid="stTextArea"] textarea{background:transparent!important;border:0!important;outline:none!important;box-shadow:none!important;border-radius:0;padding:.45rem 0;color:#a66e7c!important;caret-color:#a66e7c;font-size:calc(1.1rem + 4pt)!important;font-weight:700!important;line-height:1.6;resize:none}
[data-testid="stTextArea"] textarea::placeholder{color:#b7a8ad;opacity:1;font-weight:700}
[data-testid="stFormSubmitButton"]{display:flex;justify-content:flex-end}
button{border-radius:12px!important}
.answer-loading{background:#fff;border:1px solid #eadde0;border-radius:20px;padding:28px;margin-top:24px}
.loading-title{display:flex;align-items:center;gap:14px;font-weight:600;color:#946371}
.loading-dots{display:inline-flex;gap:5px}
.loading-dots i{width:7px;height:7px;border-radius:50%;background:#a66e7c;animation:pulse 1.2s ease-in-out infinite}
.loading-dots i:nth-child(2){animation-delay:.15s}.loading-dots i:nth-child(3){animation-delay:.3s}
.loading-line{height:12px;margin-top:20px;border-radius:6px;background:linear-gradient(90deg,#f3edef 25%,#fbf8f9 50%,#f3edef 75%);background-size:200% 100%;animation:shimmer 1.6s linear infinite}
.loading-line.short{width:65%}
@keyframes pulse{0%,80%,100%{opacity:.3;transform:translateY(0)}40%{opacity:1;transform:translateY(-4px)}}
@keyframes arrive{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
@keyframes question-rise{from{opacity:0;transform:translateY(32px) scale(.96);color:#a66e7c}to{opacity:1;transform:translateY(0) scale(1);color:#302a2c}}
@keyframes question-mark{from{opacity:0;transform:scale(.65) rotate(-12deg)}to{opacity:1;transform:scale(1) rotate(0)}}
@keyframes shimmer{to{background-position:-200% 0}}
@media(max-width:600px){.block-container{padding-top:3rem}[data-testid="stForm"]{padding:1rem}.st-key-answer_dashboard [data-testid="stHorizontalBlock"]{flex-direction:column}.st-key-answer_dashboard [data-testid="stColumn"]{width:100%!important;flex:1 1 100%!important}.st-key-answer_overview,[class*="st-key-answer_card_"],[class*="st-key-analysis_card_"],[class*="st-key-financial_card_"]{padding:1.2rem}}
@media(prefers-reduced-motion:reduce){.loading-dots i,.loading-line,.hero-title,.hero-subtitle,.question-enter .question-title,.question-enter .question-mark,[data-testid="stForm"]{animation:none}}
</style>
"""
LOADING_HTML = """<div class="answer-loading" role="status" aria-live="polite" aria-busy="true">
<div class="loading-title"><span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span>
답변을 준비하고 있어요</div><div aria-hidden="true"><div class="loading-line"></div>
<div class="loading-line"></div><div class="loading-line short"></div></div></div>"""


def configure_secrets():
    """Community Cloud secrets and local .env use the same backend configuration."""
    names = ('OPENAI_API_KEY', 'NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD', 'NEO4J_DATABASE', 'BULSAE_LLM_MODEL', 'BULSAE_REVIEW_MODEL')
    try:
        for name in names:
            if name in st.secrets and not os.getenv(name):
                os.environ[name] = str(st.secrets[name])
    except (FileNotFoundError, KeyError):
        pass


def run_question(question):
    # Reuse the Python flow directly: no browser-to-localhost HTTP bridge.
    from bulsae.graphrag.web_server import answer_question
    key = (question.strip(), os.getenv('BULSAE_LLM_MODEL'), os.getenv('BULSAE_REVIEW_MODEL'))
    now = time.monotonic()
    cache = {k: v for k, v in st.session_state.get('answer_cache', {}).items()
             if 0 <= now - v['stored_at'] < 300}
    st.session_state['answer_cache'] = cache
    if key in cache:
        cached = deepcopy(cache[key]['response'])
        cached.setdefault('trace', {})['session_cache'] = {
            'hit': True, 'age_seconds': round(now - cache[key]['stored_at']), 'ttl_seconds': 300}
        return cached
    result = answer_question(question)
    if result.get('status') == 'answered':
        if len(cache) >= 5:
            del cache[min(cache, key=lambda k: cache[k]['stored_at'])]
        cache[key] = {'stored_at': time.monotonic(), 'response': deepcopy(result)}
        st.session_state['answer_cache'] = cache
    return result


def queue_question(question=None):
    question = (question if question is not None else st.session_state.get('question_input', '')).strip()
    if question and not st.session_state.get('is_loading'):
        st.session_state['active_question'] = question
        st.session_state['pending_question'] = question
        st.session_state['is_loading'] = True
        st.session_state.pop('result', None)


def start_new_question():
    for name in ('active_question', 'pending_question', 'result', 'completed_question', 'question_input'):
        st.session_state.pop(name, None)
    st.session_state['is_loading'] = False


def http_url(value):
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ('http', 'https') and parsed.netloc else None
    except (ValueError, TypeError):
        return None


def report_text(result):
    profiles = result.get('company_profiles') or ([result['company_overview']] if result.get('company_overview') else [])
    blocks = []
    for profile in profiles:
        fields = '\n'.join(f"{f['label']}: {f['value']}" for f in profile.get('fields', []))
        news = '\n'.join(f"{n['heading']} ({publication_day(n.get('published_at'))}, 기사 발행): {n['text']}" for n in profile.get('news', []))
        blocks.append('\n'.join(x for x in (profile.get('name',''), fields,
            '주요 사업: ' + profile['business'] if profile.get('business') else '', news) if x))
    return '\n\n'.join(blocks + [result.get('answer', '')]) + '\n\n출처\n' + '\n'.join(
        f"[{s['number']}] {s['title']}\n{s['url']}" for s in result.get('sources', []))


def basket_report(items):
    """Combine saved snapshots without generating or rewriting their content."""
    sections = ['CONNECT 보고서', f'담은 답변 {len(items)}건']
    for index, item in enumerate(items, 1):
        result = item['result']
        sections.append(f"{'=' * 40}\n{index}. {result.get('question', '질문')}\n\n{report_text(result)}")
    return '\n\n'.join(sections)


def set_page(page):
    st.session_state['current_page'] = page


def use_local_basket():
    """Disk storage is available only when explicitly enabled on a local host."""
    return os.getenv('BULSAE_LOCAL_BASKET') == '1'


def get_basket_items():
    if use_local_basket():
        return report_basket.list_answers()
    return list(st.session_state.get('report_basket', []))


def save_basket_answer(result):
    if use_local_basket():
        return report_basket.save_answer(result)
    items = st.session_state.get('report_basket', [])
    item_id = report_basket.answer_id(result)
    if any(item['id'] == item_id for item in items):
        return False
    st.session_state['report_basket'] = [{'id': item_id,
        'saved_at': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
        'result': deepcopy(result)}] + items
    return True


def remove_basket_answer(item_id):
    if use_local_basket():
        report_basket.remove_answer(item_id)
    else:
        st.session_state['report_basket'] = [item for item in st.session_state.get('report_basket', [])
                                             if item['id'] != item_id]


def render_basket(items):
    box_icon = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
                'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5z"/>'
                '<path d="m3.5 7.5 8.5 4.6 8.5-4.6M12 12.1V21M8 5.1l8.5 4.7"/></svg>')
    with st.container(key='basket_intro', horizontal=True, horizontal_alignment='distribute',
                      vertical_alignment='center', wrap=True):
        st.markdown('<h1 class="basket-title">보고서 장바구니</h1>', unsafe_allow_html=True)
        if items:
            st.download_button('보고서 생성하기', data=basket_report(items),
                               file_name='CONNECT_모아보기_보고서.txt', mime='text/plain',
                               key='download_basket_report', type='primary', on_click='ignore', icon=':material/auto_awesome:')
    if not use_local_basket():
        st.caption('이 브라우저 세션에서만 보관돼요. 페이지를 새로고침하거나 닫기 전에 보고서를 저장해 주세요.')
    if not items:
        st.markdown('<div class="basket-empty"><div class="basket-empty-icon">' + box_icon +
                    '</div><p class="basket-empty-title">아직 담아둔 답변이 없어요</p>'
                    '<p class="basket-empty-copy">궁금한 기업을 살펴본 뒤<br>'
                    '마음에 드는 답변을 장바구니에 담아보세요.</p></div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="basket-list-heading">담아둔 답변 <span>{len(items)}개의 답변</span></div>',
                unsafe_allow_html=True)
    for item in items:
        result = item['result']
        with st.container(border=True, key='basket_card_' + item['id']):
            with st.container(horizontal=True, horizontal_alignment='distribute', vertical_alignment='center'):
                st.subheader(result.get('question') or '저장한 답변')
                if st.button('장바구니에서 빼기', key='basket_remove_' + item['id'],
                             icon=':material/close:', type='tertiary', help='장바구니에서 빼기'):
                    remove_basket_answer(item['id'])
                    st.rerun()
            saved = publication_day(item['saved_at'])
            if saved:
                st.caption('담은 날짜 · ' + saved)
            preview = ' '.join((result.get('lead') or result.get('answer') or '저장된 답변').split())
            st.write(preview[:240] + ('…' if len(preview) > 240 else ''))
            with st.expander('답변과 출처 보기'):
                st.text(report_text(result))


def publication_day(value):
    try:
        date = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return date.astimezone(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d') if date.tzinfo else ''
    except (ValueError, TypeError):
        return ''


def render_section_cards(sections, prefix):
    for index, section in enumerate(sections):
        with st.container(key=f'{prefix}_{index}'):
            if section.get('heading'):
                st.subheader(section['heading'])
            st.write(section['text'])


def repeats_financial_amount(section, cards):
    """Hide only a standalone restatement of a displayed metric, not comparisons."""
    text = section.get('text', '').strip()
    for card in cards:
        if not all(card.get(k) for k in ('company', 'year', 'period', 'scope', 'label')):
            continue
        label = r'매출(?:액)?' if card['label'] == '매출액' else re.escape(card['label'])
        pattern = (re.escape(card['company']) + r'(?:의)?\s*' + str(card['year']) + r'년\s*' +
            re.escape(card['period']) + r'\s*' + re.escape(card['scope']) + r'\s*(?:기준(?:의|으로)?\s*)?' +
            label + r'(?:은|는|:)?\s*[\d,.\s조억만]+원(?:이에요|예요|입니다)?[.!]?')
        if re.fullmatch(pattern, text):
            return True
    return False


def financial_heading(heading):
    """Move internal scope prefixes out of the way without losing their meaning."""
    prefix = '연결 사업 · '
    if heading.startswith(prefix):
        return heading[len(prefix):].strip() + ' (연결 사업 기준)'
    return heading


def render_financial_outline(sections):
    """Keep verified wording intact, displayed as a report outline, not tiles."""
    for section in sections:
        if section.get('heading'):
            st.markdown('#### ' + financial_heading(section['heading']))
        # New responses contain bullet lines; old responses remain intact as one
        # bullet per paragraph. Never split numbers or rewrite causal wording.
        points = [re.sub(r'^[-*•]\s+', '', line.strip())
                  for line in section.get('text', '').splitlines() if line.strip()]
        if points:
            st.markdown('\n'.join('- ' + point for point in points))


def render_financial_report(result, cards):
    sections = [s for s in result.get('sections', []) if not repeats_financial_amount(s, cards)]
    facts = [s for s in sections if s.get('kind') != 'interpretation']
    interpretations = [s for s in sections if s.get('kind') == 'interpretation']
    if result.get('lead') and not repeats_financial_amount({'text':result['lead']}, cards):
        st.write(result['lead'])
    if facts:
        labels = {c['label'] for c in cards}
        metric = '매출·영업이익' if {'매출액', '영업이익'} <= labels else ('매출' if '매출액' in labels else '영업이익')
        with st.container(key='financial_factors'):
            st.subheader(metric + ' 주요 요인')
            render_financial_outline(facts)
    if interpretations:
        with st.container(key='financial_analysis_report'):
            st.subheader('✦ AI 통합분석')
            render_financial_outline(interpretations)
    if result.get('analysis_notice'):
        st.caption(result['analysis_notice'])


def korean_won(value):
    """Display integer KRW without rounding or changing the sourced amount."""
    if isinstance(value, bool) or not isinstance(value, int):
        return f'{value:,}원'
    amount = abs(value)
    groups = []
    for unit in ('', '만', '억', '조', '경'):
        amount, part = divmod(amount, 10000)
        if part:
            groups.append(f'{part:,}{unit}')
        if not amount:
            break
    if amount:  # Beyond supported Korean units: retain the exact numeric amount.
        return f'{value:,}원'
    return ('−' if value < 0 else '') + (' '.join(reversed(groups)) or '0') + '원'


def financial_period_caption(card):
    st.caption(' · '.join(str(x) for x in (
        f"{card['year']}년" if card.get('year') else None,
        card.get('period'), card.get('scope')) if x))


def render_answer(result):
    with st.container(key='answer_dashboard'):
        profiles = result.get('company_profiles') or ([result['company_overview']] if result.get('company_overview') else [])
        for profile_index, profile in enumerate(profiles):
            st.subheader((profile.get('name') + ' · ' if len(profiles)>1 and profile.get('name') else '') + '기업 한눈에 보기')
            if profile.get('fields'):
                with st.container(key=f'company_profile_{profile_index}'):
                    cells = ''.join('<div class="company-profile-item' + (' company-profile-item--wide' if field.get('field') == 'industry' or field.get('label') == '업종' else '') + '"><div class="company-profile-label">' + escape(str(field['label'])) +
                        '</div><div class="company-profile-value">' + escape(str(field['value'])) + '</div></div>'
                        for field in profile['fields'])
                    st.markdown('<div class="company-profile-grid">' + cells + '</div>', unsafe_allow_html=True)
            else:
                st.write('확인된 기본정보가 없어요.')
            st.subheader('주요 사업')
            st.write(profile.get('business') or '확인된 주요 사업 정보가 없어요.')
            st.subheader('최근 소식')
            for news_index, item in enumerate(profile.get('news', [])[:3]):
                with st.container(key=f'company_news_{profile_index}_{news_index}'):
                    st.subheader(item['heading'])
                    if publication_day(item.get('published_at')):
                        st.caption('기사 발행일 · ' + publication_day(item['published_at']))
                    st.write(item['text'])
            if not profile.get('news'):
                st.write('최근 소식 검색을 완료하지 못했어요.' if profile.get('recent_status') == 'unavailable'
                         else '확인된 최근 소식이 없어요.')
        events = result.get('event_cards') or []
        if events:
            with st.container(key='event_count'):
                st.subheader(f'확인된 참석 행사 {len(events)}건')
            for index, event in enumerate(events):
                with st.container(key=f'event_row_{index}'):
                    st.subheader(event['name'])
                    st.caption(' · '.join(filter(None, (
                        f"{event['year']}년" if event.get('year') else '',
                        ', '.join(event['participants'])))))
                    if event.get('description'):
                        st.markdown('**행사 소개**')
                        st.write(event['description'])
                    if event.get('activity'):
                        st.markdown('**발표·활동 내용**')
                        st.write(event['activity'])
                    if not event.get('description') and not event.get('activity'):
                        st.write('참석 사실이 확인됐어요. 구체적인 행사 설명과 발표 내용은 자료에 없어요.')
        cards = result.get('financial_cards') or []
        if cards:
            st.subheader('재무 한눈에 보기')
            revenues = [(i, card) for i, card in enumerate(cards) if card['label'] == '매출액']
            other_cards = [(i, card) for i, card in enumerate(cards) if card['label'] != '매출액']
            for index, card in revenues:
                with st.container(key=f'financial_card_{index}'):
                    st.markdown(
                        f'<div class="revenue-label">{escape(card.get("company") or "")} · 매출액</div>'
                        f'<div class="revenue-amounts"><span class="revenue-value">{card["value"]:,}원</span>'
                        f'<span class="revenue-korean">{escape(korean_won(card["value"]))}</span></div>',
                        unsafe_allow_html=True,
                    )
                    financial_period_caption(card)
            for index, card in other_cards:
                with st.container(key=f'financial_card_{index}'):
                    st.metric(f"{card.get('company') or ''} · {card['label']}", f"{card['value']:,}원")
                    financial_period_caption(card)

        if cards and not events:
            render_financial_report(result, cards)
            return

        sections = result.get('sections') or []
        basic = [section for section in sections if section.get('section_type') != 'additional']
        if result.get('company_overview') and not result.get('company_profiles'):
            basic = []
        additional = [section for section in sections if section.get('section_type') == 'additional']
        overview = [result['lead']] if result.get('lead') else []
        if basic and not basic[0].get('heading'):
            overview.append(basic.pop(0)['text'])
        if not sections and not overview and not cards and not events and not profiles:
            overview.append(result.get('answer', '답변을 만들지 못했어요.'))
        if overview:
            with st.container(key='answer_overview'):
                for text in overview:
                    st.write(text)
        if events:
            render_financial_outline(basic)
        else:
            render_section_cards(basic, 'answer_card')
        if additional:
            if events:
                with st.container(key='event_analysis'):
                    st.subheader('✦ AI 통합분석')
                    render_financial_outline(additional)
            elif profiles:
                with st.container(key='event_analysis'):
                    st.subheader('✦ AI 통합분석')
                    render_financial_outline(additional)
            else:
                st.subheader('LLM 분석' if result.get('final_composed') else '관련 분석')
                render_section_cards(additional, 'analysis_card')
        if result.get('analysis_notice'):
            st.caption(result['analysis_notice'])


def render_quality(result):
    with st.expander('검색 과정과 근거 · 품질 확인', expanded=False):
        trace = result.get('trace', {})
        st.caption('실행 ID: ' + result.get('run_id', '없음'))
        if result.get('created_at'):
            st.caption('실행 시각: ' + result['created_at'])
        columns = st.columns(4)
        columns[0].metric('조회 기록', f"{trace.get('retrieved_records', 0)}건")
        columns[1].metric('답변 출처', f"{len(result.get('sources', []))}건")
        columns[2].metric('답변 경로 최대', f"{trace.get('hops', 0)}홉")
        cache_info = trace.get('session_cache', {})
        columns[3].metric('최초 처리 시간' if cache_info.get('hit') else '처리 시간', f"{result.get('elapsed_ms', 0) / 1000:.1f}초")
        if cache_info.get('hit'):
            st.caption(f"같은 세션에서 {cache_info['age_seconds']}초 전에 생성한 답변을 재사용했어요. 새 DB 조회는 하지 않았어요.")
        st.write(' → '.join(trace.get('steps', [])))
        if trace.get('executed_nodes'):
            st.caption('실제 실행 단계: ' + ' → '.join(trace['executed_nodes']))
        plan = trace.get('search_plan')
        if plan:
            requested = ['회사 기본정보'] if plan.get('company_overview') else []
            if plan.get('financial'):
                requested.append('재무·비교')
            if plan.get('executive_events'):
                requested.append('대표·회장 행사')
            if plan.get('graph_context'):
                requested.append('관련 관계·기사')
            st.caption('질문 분석: ' + (' · '.join(requested) if requested else '일반 검색') +
                       (' (대체 규칙 사용)' if plan.get('source') == 'rule_fallback' else ''))
        for component in trace.get('components', []):
            st.caption('요청별 실행 · ' + component['task'] + ': ' +
                       (' → '.join(component.get('executed_nodes', [])) or component['status']))
        if trace.get('node_timings'):
            st.caption('단계별 시간: ' + ' · '.join(
                f"{'/'.join(t['nodes'])} {t['elapsed_ms'] / 1000:.1f}초" for t in trace['node_timings']))
        if trace.get('service_version'):
            st.caption('서비스 버전: ' + trace['service_version'])
        if trace.get('document_search_count'):
            st.caption(f"그래프와 별도로 원문 {trace['document_search_count']}건을 검색해 보완했어요.")
        if trace.get('related_records'):
            st.caption(f"관련 분석 근거 {trace['related_records']}건 중 검사를 통과한 분석 {trace.get('related_points', 0)}개를 추가했어요.")
        diagnostics = trace.get('related_diagnostics', {})
        if diagnostics.get('search_queries'):
            st.caption(f"추가 분석 검색 {len(diagnostics['search_queries'])}개 관점 · 선택한 문서 {diagnostics.get('selected_documents', 0)}건")
            for query in diagnostics['search_queries']:
                st.text(query)
        paths = sorted(trace.get('graph_paths', []), key=lambda p: (not p['used_in_answer'], -p['hops']))
        if paths:
            st.markdown('#### 실제 조회한 그래프 경로')
            st.caption(f"탐색한 경로 {len(paths)}개 · 탐색 최대 {trace.get('retrieved_graph_hops', 0)}홉 · 답변에 사용한 경로 {sum(p['used_in_answer'] for p in paths)}개")
            st.caption('관계의 근거 문서 ID로 기사를 읽습니다. 기사까지의 ID 조회는 그래프 홉에 포함하지 않아요.')
            index = st.selectbox('조회 경로', range(len(paths)), format_func=lambda i:
                ('답변에 사용' if paths[i]['used_in_answer'] else '조회 후 미채택') +
                f" · {paths[i]['hops']}홉 · " + paths[i]['edges'][0]['from_name'] + ' → ' +
                ' → '.join(e['to_name'] for e in paths[i]['edges']), key='graph_path_selection')
            selected = paths[index]
            st.code('\n'.join(f"{e['from_name']} — {RELATIONS.get(e['relation'], e['relation'])} ({e['relation']}) → {e['to_name']}"
                               for e in selected['edges']), language=None, wrap_lines=True)
            for edge in selected['edges']:
                st.caption(f"관계 기록: {edge['observation_id']} · 문서 ID: {edge['document_id']}")
                url = http_url(edge.get('url'))
                if url:
                    st.markdown(f"[{edge.get('title') or '관계 근거 기사'}]({url})")
        reasons = diagnostics.get('fallback_reasons', [])
        if reasons:
            st.markdown('#### 원문 검색으로 보완한 항목')
            for item in reasons:
                st.write(f"{item['company']} · {item['facet']}: {item['reason']}")
        connections = trace.get('connections', [])
        chains = set()
        for work in connections:
            if work['relation'] != 'WORKS_AT':
                continue
            for event in connections:
                if (event['relation'] == 'PARTICIPATED_IN' and work['from'] == event['from']
                        and work['source_number'] == event['source_number']):
                    chains.add((work['to'], work['from'], event['to']))
        if chains:
            st.markdown('#### 그래프 연결')
            for company, person, event in sorted(chains):
                st.code(f'{company} ← 재직 — {person} — 참여 → {event}', language=None, wrap_lines=True)
        if connections:
            st.dataframe([{'출발 노드': c['from'], '관계': f"{RELATIONS.get(c['relation'], c['relation'])} ({c['relation']})",
                           '도착 노드': c['to'], '출처 번호': c['source_number'],
                           '관계 기록 ID': c.get('observation_id') or '별도 ID 없음'} for c in connections],
                          hide_index=True, width='stretch')
        elif trace.get('mode') == 'company_info':
            st.write('기업 ID로 기본 정보를 조회했어요. 이 답변에는 그래프 관계 탐색을 사용하지 않았어요.')
        else:
            st.write('이 응답에는 표시할 그래프 관계 경로가 없어요.')
        st.markdown('#### 답변에 사용한 자료')
        for source in result.get('sources', []):
            with st.container(border=True):
                st.write(f"[{source['number']}] {source['title']}")
                st.caption('근거 ID: ' + (source.get('document_id') or '자료 ID 없음'))
                if source.get('source_kind') == 'document':
                    st.caption('원문 검색에서 찾은 근거')
                if source.get('source_file'):
                    st.caption('수집 파일: ' + source['source_file'])
                url = http_url(source.get('url'))
                if url:
                    st.link_button('원문 기사·자료 열기', url)
                for quote in source.get('quotes', []):
                    st.text(quote)
        if not result.get('sources'):
            st.write('답변에 사용한 출처가 없어요.')
        st.caption('응답 상태: ' + result.get('status', 'unknown') + ' · 모델: ' + trace.get('model', '표시 정보 없음'))
        st.download_button('품질 확인 기록 다운로드', data=json.dumps(result, ensure_ascii=False, indent=2),
                           file_name='connect-' + result.get('run_id', 'answer') + '.json',
                           mime='application/json', key='download_trace', on_click='ignore')


def main():
    st.set_page_config(page_title='CONNECT · 기업 조사', page_icon='✳', layout='wide')
    configure_secrets()
    st.markdown(CSS, unsafe_allow_html=True)
    try:
        basket_items = get_basket_items()
    except (OSError, ValueError, sqlite3.Error):
        basket_items = []
        st.error('저장한 답변을 불러오지 못했어요. 로컬 저장 공간을 확인해 주세요.')
    if basket_items:
        st.markdown(f'<style>.st-key-nav_basket::after{{content:"{len(basket_items)}";position:absolute;'
                    'right:0;bottom:0;min-width:19px;height:19px;padding:0 4px;box-sizing:border-box;'
                    'display:flex;align-items:center;justify-content:center;border-radius:999px;'
                    'background:#a86f81;color:#fff;border:2px solid #faf7f8;font-size:10px;font-weight:700;'
                    'line-height:1;pointer-events:none}</style>', unsafe_allow_html=True)
    with st.container(key='top_navigation', horizontal=True, horizontal_alignment='right'):
        if st.session_state.get('current_page') == 'basket':
            st.button('뒤로 가기', key='nav_question', type='tertiary', help='질문 화면으로 돌아가기',
                      on_click=set_page, args=('question',), icon=':material/arrow_back:')
        else:
            st.button('보고서 장바구니', key='nav_basket', type='tertiary', help='보고서 장바구니',
                      on_click=set_page, args=('basket',), icon=':material/shopping_cart:')
    if st.session_state.get('current_page') == 'basket':
        render_basket(basket_items)
        return
    pending = st.session_state.pop('pending_question', None)
    result = st.session_state.get('result')
    if pending or result:
        question = pending or st.session_state.get('active_question') or result.get('question', '')
        motion = ' question-enter' if pending else ''
        st.markdown(
            f'<div class="question-heading{motion}"><span class="question-mark" aria-hidden="true">Q</span>'
            f'<h1 class="question-title">{escape(question)}</h1></div>', unsafe_allow_html=True)
        if pending:
            st.markdown(LOADING_HTML, unsafe_allow_html=True)
            try:
                st.session_state['result'] = {**run_question(pending), 'question': pending}
            except Exception as exc:
                frames = []
                tb = exc.__traceback__
                while tb is not None:
                    frames.append(tb.tb_frame.f_code.co_name)
                    tb = tb.tb_next
                settings = {name: bool(os.getenv(name)) for name in
                            ('OPENAI_API_KEY', 'NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD')}
                logger.error('Question processing failed: %s; functions=%s; settings_present=%s',
                             type(exc).__name__, ' > '.join(frames), settings)
                st.session_state['result'] = {'question':pending, 'status':'error',
                    'answer':'지금은 답변을 불러올 수 없어요. 잠시 후 다시 시도해 주세요.',
                    'sections':[], 'sources':[], 'trace':{}}
            finally:
                st.session_state['is_loading'] = False
            st.rerun()
        with st.container(key='dashboard_toolbar', horizontal=True, horizontal_alignment='right'):
            st.button('새 질문', key='new_question', type='tertiary', on_click=start_new_question)
            if result.get('status') == 'error':
                st.button('다시 시도', key='retry_question', on_click=queue_question, args=(question,))
            else:
                st.download_button('답변 저장', data=report_text(result), file_name='CONNECT_기업조사.txt',
                                   mime='text/plain', key='download_answer', on_click='ignore', type='tertiary')
                if st.button('장바구니 담기', key='save_to_basket', type='primary', icon=':material/shopping_cart:'):
                    try:
                        saved = save_basket_answer(result)
                        st.session_state['basket_message'] = '보고서 장바구니에 담았어요.' if saved else '이미 장바구니에 담긴 답변이에요.'
                        st.rerun()
                    except (OSError, ValueError, sqlite3.Error):
                        st.error('답변을 저장하지 못했어요. 로컬 저장 공간을 확인해 주세요.')
        if st.session_state.get('basket_message'):
            message = escape(st.session_state.pop('basket_message'))
            st.markdown(f'<div class="basket-toast" role="status" aria-live="polite">{message}</div>',
                        unsafe_allow_html=True)
        render_answer(result)
        render_quality(result)
        return

    st.markdown('<h1 class="hero-title">기업 정보는 한눈에, 분석은 더 깊게</h1><p class="hero-subtitle">흩어진 뉴스와 재무, 기업 간 관계를 연결해 궁금한 기업을 분석합니다.</p>', unsafe_allow_html=True)
    with st.form('question_form', border=False):
        question = st.text_area('질문하기', key='question_input', max_chars=1000, height=110,
                                placeholder='무엇이든 질문해 주세요', label_visibility='collapsed')
        submitted = st.form_submit_button('질문하기 →', key='submit_question', type='primary', on_click=queue_question)
    if submitted and not question.strip():
        st.warning('궁금한 기업과 질문을 입력해 주세요.')


if __name__ == '__main__':
    main()
