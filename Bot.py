"""
텔레그램 야후파이낸스 OHLC 조회 봇
------------------------------------
사용법: 텔레그램 채팅창에 티커(예: AAPL, TQQQ, ^GSPC, BRK-B)만 입력하면
2025-01-01부터 오늘까지의 배당/분할 반영(수정) OHLC 데이터를
CSV 파일로 만들어 채팅창에 전송합니다.
"""

import os
import re
import logging
from datetime import date

import pandas as pd
import yfinance as yf
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# 서버 배포 시 환경변수로 주입 (코드에 토큰을 직접 적지 마세요)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

DEFAULT_START = "2025-01-01"
TICKER_PATTERN = re.compile(r"^[A-Za-z0-9\.\-\^=]{1,15}$")  # AAPL, BRK-B, ^GSPC, KRW=X 등 허용
TMP_DIR = "/tmp/ohlc_bot"
os.makedirs(TMP_DIR, exist_ok=True)


# ------------------------------------------------------------------
# 데이터 조회
# ------------------------------------------------------------------
def fetch_ohlc(ticker: str, start: str = DEFAULT_START, end: str | None = None) -> pd.DataFrame:
    """야후파이낸스에서 배당/분할이 반영된(auto_adjust) OHLC를 가져온다."""
    if end is None:
        end = date.today().strftime("%Y-%m-%d")

    df = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=True,   # 배당·분할 반영된 수정 OHLC
        actions=False,
        progress=False,
        threads=False,
    )

    if df.empty:
        return df

    # yfinance가 종종 멀티인덱스 컬럼을 반환하는 경우 방지
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df[["Open", "High", "Low", "Close"]] = df[["Open", "High", "Low", "Close"]].round(4)
    return df


# ------------------------------------------------------------------
# 텔레그램 핸들러
# ------------------------------------------------------------------
async def handle_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw_text = (update.message.text or "").strip()
    ticker = raw_text.upper()

    if not TICKER_PATTERN.match(ticker):
        await update.message.reply_text(
            "티커 형식을 확인해주세요. 예: AAPL, TQQQ, SOXL, BRK-B, ^GSPC"
        )
        return

    status_msg = await update.message.reply_text(f"🔎 {ticker} 데이터를 조회하고 있어요...")

    try:
        df = fetch_ohlc(ticker)
    except Exception:
        logger.exception("yfinance 조회 실패: %s", ticker)
        await status_msg.edit_text(f"⚠️ '{ticker}' 데이터를 가져오는 중 오류가 발생했어요.")
        return

    if df.empty:
        await status_msg.edit_text(
            f"'{ticker}'에 대한 데이터를 찾을 수 없어요. 티커가 맞는지 확인해주세요."
        )
        return

    csv_path = os.path.join(TMP_DIR, f"{ticker}_ohlc.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    end_date = df["Date"].iloc[-1]
    caption = (
        f"📊 {ticker} 수정(배당·분할 반영) OHLC\n"
        f"기간: {DEFAULT_START} ~ {end_date}\n"
        f"거래일수: {len(df)}일"
    )

    try:
        with open(csv_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"{ticker}_ohlc_{DEFAULT_START}_to_{end_date}.csv",
                caption=caption,
            )
        await status_msg.delete()
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "티커를 텍스트로 입력해주세요. 예: AAPL"
    )


# ------------------------------------------------------------------
# 엔트리 포인트
# ------------------------------------------------------------------
def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "환경변수 TELEGRAM_BOT_TOKEN이 설정되지 않았습니다. "
            "예: export TELEGRAM_BOT_TOKEN='123456:ABC-...'"
        )

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ticker))

    logger.info("봇을 시작합니다 (polling 모드)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
