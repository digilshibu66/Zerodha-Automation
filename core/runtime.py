from browser_monitor import chrome_running
from telegram_manager import send_message
from strategy_engine import simulate_trade


def main():

    print("🚀 Starting Trading Automation Bot")

    if chrome_running():

        print("✅ Chrome Running")
        send_message("✅ Chrome Running")

    else:

        print("❌ Chrome Not Running")
        send_message("❌ Chrome Not Running")

        return


    send_message("🚀 Bot Started Successfully")

    simulate_trade()


if __name__ == "__main__":
    main()