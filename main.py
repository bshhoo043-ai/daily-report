import os
import feedparser
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
import hashlib
from openai import OpenAI

SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_APP_PASSWORD = os.environ.get("SENDER_APP_PASSWORD")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
RECIPIENTS = os.environ.get("RECIPIENTS", "sam@sigmaship.co.kr,john@sigmaship.co.kr").split(",")

client = OpenAI(api_key=OPENAI_API_KEY)

KEYWORDS = [
    "iran", "hormuz", "strait of hormuz", "tehran", "iran war", "iran conflict",
    "tanker", "vlcc", "suezmax", "aframax", "oil", "crude", "brent", "wti",
    "trump", "geopolit", "persian gulf", "bab al-mandeb", "bab el-mandeb", "houthi", "saudi",
    "uae", "iraq", "kuwait", "qatar", "shipping", "maritime", "sanctions", "blockade"
]

FEEDS = [
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Maritime Executive", "https://maritime-executive.com/articles.rss"),
    ("Splash247", "https://splash247.com/feed/"),
    ("Reuters", "https://news.google.com/rss/search?q=site:reuters.com+(Iran+OR+Hormuz+OR+tanker+OR+oil)+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("CNBC", "https://news.google.com/rss/search?q=site:cnbc.com+(Iran+OR+Hormuz+OR+oil)+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Guardian", "https://news.google.com/rss/search?q=site:theguardian.com+(Iran+OR+Hormuz)+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Iran International", "https://news.google.com/rss/search?q=site:iranintl.com+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("General", "https://news.google.com/rss/search?q=(Iran+OR+Hormuz+OR+%22Strait+of+Hormuz%22)+(war+OR+tanker+OR+oil+OR+Trump)+when:1d&hl=en-US&gl=US&ceid=US:en"),
]

def is_relevant(title, summary=""):
    text = (title + " " + summary).lower()
    return any(kw in text for kw in KEYWORDS)

def summarize_korean(title, summary):
    try:
        prompt = f"""다음 뉴스 제목과 요약을 한국어로 4~5줄 정도로 자연스럽고 간결하게 요약해줘.
해운·유조선·원유 시장·지정학적 영향이 있으면 반드시 포함해.
불필요한 인사말 없이 내용만 작성해.

제목: {title}
내용: {summary}
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=320
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Summary error: {e}")
        return "요약 생성 중 오류가 발생했습니다."

def generate_sections(news_items):
    news_text = ""
    for i, item in enumerate(news_items[:12], 1):
        news_text += f"{i}. {item['title']}\n{item['summary'][:300]}\n\n"

    prompt = f"""당신은 해운·탱커 시장 전문 애널리스트입니다.
아래 최근 12시간 내 이란/호르무즈/유조선 관련 뉴스들을 바탕으로, 다음 3개 섹션을 한국어로 작성해주세요.

[작성 규칙]
- 각 섹션은 간결하고 객관적으로 작성
- 해운/유조선 시장에 미치는 영향이 있으면 반드시 언급
- 불필요한 인사말이나 서론 없이 바로 본문만 작성

[섹션 1: 해상 안보동향]
- 호르무즈 해협(SOH) 통항 현황을 기사 내용 기반으로 요약
- Bab el-Mandeb 해협 통항/안보 현황 요약
- 선박 공격, 나포, 경고 등 안보 관련 이슈가 있으면 포함
- 마지막에 아래 링크를 참고용으로 넣어줘:
  · SOH: https://tankermap.com/analytics/straits/hormuz
  · Bab el-Mandeb: https://tankermap.com/analytics/straits/bab-el-mandeb

[섹션 2: 선박 용선현황]
- 단기 수송 안정성: 기존 시황 코멘트 스타일로 작성 (VLCC/Suezmax/Aframax, 대서양/중동/홍해 등 지역별 흐름을 기사 기반으로 간결하게)
- 중장기 변화: 기사들을 종합해서 톤마일, 선복, 리스크 프리미엄, 우회 항로 등 중장기 시사점 정리

[섹션 3: 정책 및 외교 상황]
- 미국(트럼프)·이란·관련국(중국, UAE, 오만 등)의 정책·제재·외교 동향을 정리
- 경제 제재, 봉쇄, 협상 관련 내용 중심으로

뉴스 목록:
{news_text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Section generation error: {e}")
        return "섹션 생성 중 오류가 발생했습니다."

def get_entries(hours=12):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    seen = set()
    items = []

    for source, url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title:
                    continue

                title_hash = hashlib.md5(title.lower().encode()).hexdigest()
                if title_hash in seen:
                    continue

                published = None
                if hasattr(entry, "published"):
                    try:
                        published = date_parser.parse(entry.published)
                        if published.tzinfo is None:
                            published = published.replace(tzinfo=timezone.utc)
                    except:
                        published = None

                if published and published < cutoff:
                    continue

                summary = entry.get("summary", "")[:450]
                if not is_relevant(title, summary):
                    continue

                seen.add(title_hash)
                items.append({
                    "source": source,
                    "title": title,
                    "link": entry.get("link", ""),
                    "summary": summary,
                    "published": published
                })
        except Exception as e:
            print(f"Error fetching {source}: {e}")

    items.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:15]

def create_html(items, sections_text):
    html = f"""
    <html>
    <body style="font-family: 'Malgun Gothic', '맑은 고딕', AppleGothic, sans-serif; line-height: 1.7; color: #333; max-width: 720px; margin: 0 auto; background: #f4f6f8;">
       
        <div style="background: white; padding: 22px 28px; border-bottom: 3px solid #c0392b; margin-bottom: 22px;">
            <div style="text-align: center;">
                <div style="font-size: 20px; font-weight: 700; color: #c0392b;">
                    IRAN WAR STATUS
                </div>
            </div>
        </div>

        <div style="background: white; padding: 20px 24px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.07);">
            <div style="font-size: 14.5px; color: #333; white-space: pre-line; line-height: 1.75;">
{sections_text}
            </div>
        </div>

        <h2 style="font-size: 17px; color: #1a5276; margin: 0 0 16px 0; padding: 0 8px;">
            주요 뉴스 요약
        </h2>
    """

    if not items:
        html += "<p style='padding: 0 8px;'>관련 뉴스가 없습니다.</p>"
    else:
        for i, e in enumerate(items, 1):
            pub = e["published"].strftime("%m-%d %H:%M UTC") if e["published"] else ""
            korean = summarize_korean(e["title"], e["summary"])
            html += f"""
            <div style="background: white; padding: 16px 20px; margin-bottom: 14px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.07);">
                <div style="font-size: 12px; color: #888; margin-bottom: 5px;">{e['source']} | {pub}</div>
                <h3 style="margin: 0 0 8px 0; font-size: 15.5px; color: #222;">{i}. {e['title']}</h3>
                <div style="font-size: 14px; color: #444; line-height: 1.7; white-space: pre-line;">{korean}</div>
                <div style="margin-top: 10px;">
                    <a href="{e['link']}" style="color: #0066cc; font-size: 13px; text-decoration: none;">원문 보기 →</a>
                </div>
            </div>
            """

    html += """
        <p style="font-size: 12px; color: #888; text-align: center; margin-top: 35px;">
            시그마해운(주) | Iran / Hormuz Daily Brief
        </p>
    </body>
    </html>
    """
    return html

def send_email(html_content):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Iran/Hormuz Brief] {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
    print("Email sent successfully to:", RECIPIENTS)

if __name__ == "__main__":
    print("Collecting news (last 12h)...")
    items = get_entries(hours=12)
    print(f"News items: {len(items)}")

    print("Generating sections...")
    sections = generate_sections(items)

    html = create_html(items, sections)
    send_email(html)
