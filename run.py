# this script runs the main.py script and restarts the whole process when there is an error encountered

import subprocess
import time
import os

curr_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(curr_dir)

while True:
    try:
        print("\n\nINITIATING SCRIPT AGAIN\n\n")
        process = subprocess.Popen(['python', 'main.py'])
        process.wait()

    except Exception as e:
        print(f"Error occurred: {e}")
        print("Restarting the script...")
        time.sleep(30)
