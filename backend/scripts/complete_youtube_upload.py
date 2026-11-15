#!/usr/bin/env python3
"""
Fully automated publisher for YouTube Shorts in Chrome.
Monitors YouTube Studio dialog, auto-fills metadata, clicks Next, sets Public, and publishes!
"""

import subprocess
import time
import json
import sys

TITLE = "Why Learning Chess Is Pure Propaganda 😭♟️"
DESCRIPTION = """Why Learning Chess Is Pure Propaganda

Streamer: Botez Sisters
Clipped live with SupoClip AI.

#shorts #botez #botezlive #botezsisters #alexandrabotez #andreabotez #datingadvice #trending #fyp
"""

def run_js(code):
    cmd = [
        "osascript", "-e",
        f"""
        tell application "Google Chrome"
            tell active tab of window 1
                execute javascript {json.dumps(code)}
            end tell
        end tell
        """
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip()

def fill_details():
    script = f"""
    (function() {{
        var titleBox = document.querySelector("#title-textarea #textbox") || document.querySelector("ytcp-social-suggestions-textbox #textbox") || document.querySelector("#textbox[aria-label*='title']");
        if (!titleBox) return "WAITING";

        // Set Title
        titleBox.focus();
        titleBox.innerText = {json.dumps(TITLE)};
        titleBox.dispatchEvent(new Event('input', {{ bubbles: true }}));

        // Set Description
        var descBox = document.querySelector("#description-textarea #textbox");
        if (descBox) {{
            descBox.focus();
            descBox.innerText = {json.dumps(DESCRIPTION)};
            descBox.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}

        // Select 'Not made for kids'
        var notForKids = document.querySelector("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']");
        if (notForKids) {{
            notForKids.click();
        }}

        return "FILLED";
    }})()
    """
    return run_js(script)

def click_next():
    script = """
    (function() {
        var nextBtn = document.querySelector("#next-button");
        if (nextBtn && !nextBtn.hasAttribute("disabled") && nextBtn.offsetWidth > 0) {
            nextBtn.click();
            return "CLICKED_NEXT";
        }
        return "NEXT_NOT_READY";
    })()
    """
    return run_js(script)

def set_public_and_publish():
    script = """
    (function() {
        // Select Public radio
        var publicRadio = document.querySelector("tp-yt-paper-radio-button[name='PUBLIC']");
        if (publicRadio) {
            publicRadio.click();
        }

        // Click Done/Publish
        var doneBtn = document.querySelector("#done-button");
        if (doneBtn && !doneBtn.hasAttribute("disabled") && doneBtn.offsetWidth > 0) {
            doneBtn.click();
            return "PUBLISHED";
        }
        return "WAITING_FOR_DONE";
    })()
    """
    return run_js(script)

def watch_and_publish(timeout_seconds=300):
    print("Waiting for file to be dropped into YouTube Studio dialog...")
    t0 = time.time()
    details_filled = False
    
    while time.time() - t0 < timeout_seconds:
        if not details_filled:
            status = fill_details()
            if status == "FILLED":
                print("[1/3] Video file detected! Automatically filled Title, Description, and 'Not for kids'.")
                details_filled = True
                time.sleep(2)
        else:
            # Click next through video elements & checks
            res = click_next()
            if res == "CLICKED_NEXT":
                print("[2/3] Clicked Next...")
                time.sleep(1.5)
            
            # Check if on Visibility step
            pub_res = set_public_and_publish()
            if pub_res == "PUBLISHED":
                print("[3/3] Selected Public visibility and clicked PUBLISH! Video is successfully published to YouTube!")
                return True
                
        time.sleep(1)
        
    print("Timed out waiting for file drop.")
    return False

if __name__ == "__main__":
    watch_and_publish()
