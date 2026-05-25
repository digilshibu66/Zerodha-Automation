import psutil
import pygetwindow as gw

def chrome_running():

    for process in psutil.process_iter():

        try:
            if "chrome" in process.name().lower():
                return True

        except:
            pass

    return False


if chrome_running():
    print("✅ Chrome Running")

else:
    print("❌ Chrome Not Running")


print("\nChrome Windows:\n")

titles = gw.getAllTitles()

for title in titles:

    if "chrome" in title.lower():
        print(title)