"""Global constants for the Appium GHA iOS automation project."""

import datetime
import os
from enum import Enum


GEMINI_API_KEY = "AIzaSyDqPMIawhhqj3Yopaxw-CGRPK5KApMiveo"
BUGANIZER_DEFAULT_ASSIGNEE = "enlin@google.com"
GOOGLE_SHEET_WEBHOOK_URL =  "https://script.google.com/macros/s/AKfycbwGQD4926s_AB1Lx7JLzudJGKW5LXsQtuoR4A79vcxfT1e7OCFX3SiOPo5OoxO65_Xm/exec"
# ==================== App Settings ====================
GHA_BUNDLE_ID = "com.google.Chromecast.enterprise"
iGHP_SAMPLE_APP_BUNDLE_ID = "com.google.homeplatform.sampleapp.gomezandres"
SAFARI_BUNDLE_ID = "com.apple.mobilesafari"
GHP_DEV_SITE = "https://developers.home.google.com/apis/ios/get-started"

# ==================== iOS Settings ====================
IOS_DEVICE_PASSCODE = "000000"

# ==================== Target URLs ====================
GHA_IOS_GET_STARTED_URL = "https://developers.home.google.com/apis/ios/get-started"

# ==================== Appium Server ====================
APPIUM_SERVER_URL = "http://localhost:4723"

# ==================== iOS Device Capabilities ====================
IOS_CAPABILITIES = {
    "platformName": "iOS",
    "appium:automationName": "XCUITest",
    "appium:deviceName": "Test’s iPhone",
    "appium:platformVersion": "26.5.2",
    "appium:udid": "00008030-00064DC43EEA802E",
    "appium:xcodeOrgId": "J8YMN73J2Y",
    "appium:xcodeSigningId": "jeff820915@yahoo.com.tw",
    "appium:newCommandTimeout": 3600,

}

# ==================== Partner Device (iOS query_app_state) ====================
REF2_BATTERY_CAMERA = "Ref2 Battery Camera"
ONN_WIRED_INDOOR_CAMERA = "Onn Wired Indoor Camera"

REF2_BATTERY_CAMERA_PAIRING_CODE = "621507078904738215050"
ONN_WIRED_INDOOR_CAMERA_PAIRING_CODE = "540572247205502042330"


# ==================== App States (iOS query_app_state) ====================
# 0: Not installed/Not running, 1: Not running, 2: Background (suspended), 3: Background, 4: Foreground Active
APP_STATE_FOREGROUND = 4
APP_STATE_NOT_RUNNING = 1

# ==================== Paths and Timestamp ====================
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "log")
SESSION_LOG_DIR = os.path.join(LOG_DIR, f"LOG_{TIMESTAMP}")
MAIN_LOG_DIR = os.path.join(SESSION_LOG_DIR, "Main log")
ADDITIONAL_LOG_DIR = os.path.join(SESSION_LOG_DIR, "Additional log")
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports")
REPORT_FILE = os.path.join(REPORT_DIR, f"{TIMESTAMP}.html")



# ==================== Google Home APP ====================

# CLASS_CHAIN
GHA_DEVICE_TAB_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"All devices\"`]"
GHA_FAVORITES_TAB_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Favorites\"`]"
GHA_CAMERAS_TAB_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Cameras\"`]"
GHA_LIGHTS_TAB_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Lights\"`]"
GHA_DEVICE_NAME_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"deviceTileTitleTextView\"`]"
GHA_SETUP_PAGE_DEVICE_NAME_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"title\"`]"
GHA_CAMERA_PLAYER_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"CamerazillaPlayerView\"`]"
GHA_CAMERA_RETRY_BTN_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Retry\"`]"
GHA_CAMERA_UNREACHABLE_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"The camera may be unreachable\"`]"
GHA_YES_I_M_IN_BTN_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"Yes, I'm in\"`]"
GHA_NO_THANKS_BTN_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"No thanks\"`]"
GHA_I_AGREE_BTN_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"I agree\"`]"
GHA_OK_BTN = "**/XCUIElementTypeButton[`name == \"OK\"`][2]"
GHA_CONNECTING_TITLE_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"HeaderView_headlineLabel\"`]"
GHA_ADD_TO_GOOGLE_HOME_BTN_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"Add to “Google Home\"`]"
GHA_CONNECTING_PROCESS_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"Connecting…\"`]"
GHA_CONNECTING_STATUS_CLASS_CHAIN = "**/XCUIElementTypeTextView[`name == \"Unable to Add Accessory\"`]"
GHA_CONTINUE_BTN_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Continue\"`]"
GHA_DONE_BTN_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Done\"`]"
GHA_NEXT_BTN_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Next\"`]"
GHA_COMMISSION_WINDOW_BRIDGE_CLASS_CHAIN = "**/XCUIElementTypeTextView[`name == \"Bridge\"`]"
GHA_COMMISSION_WIDOW_ALERT_CLASS_CHAIN = "**/XCUIElementTypeAlert[`name == \"Bridge Accessories Can Automatically Add to Your Home\"` OR `name == \"Additional Setup Required\"`]"
GHA_COMMISSION_WINDOW_ADD_BTN_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Add to “Google Home”\"`]"
GHA_SETTING_PAGE_CLASS_CHAIN = "**/XCUIElementTypeStaticText[`name == \"Home settings\"`]"
GHA_ACCOUNT_PICKER_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"AccountParticleButton\"`]"
GHA_REMOVE_DEVICE_BTN_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Remove device\"`]"
GHA_REMOVE_BTN_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Remove\"`]"

# PREDICATE
ACCOUNT_AVATAR_PREDICATE = 'label CONTAINS "Google Account" OR name CONTAINS "avatar" OR name CONTAINS "account"'

# ACCESSIBILITY_ID
GHA_ADD_DEVICES_BTN_ACCESSIBILITY_ID = "AddToHomeButton"
GHA_NOTIFICATION_ACCESSIBILITY_ID = "No thanks"
GHA_SET_UP_NEW_DEVICE_ACCESSIBILITY_ID = "Not now"
GHA_ACCOUNT_PARTICLE_BTN_ACCESSIBILITY_ID = "AccountParticleButton"
GHA_EXPAND_ACCOUNT_LIST = "OGLAccessibilityIdentifierAccountSelectorCollapsibleHeader"
GHA_CAMERA_PLAYER_VIEW_ACCESSIBILITY_ID = "CamerazillaPlayerView"
GHA_ADD_PAGE_DEVICE_BTN_ACCESSIBILITY_ID = "preferenceDisplayingCell_0_0"
GHA_ADD_DEVICE_WITH_PHOTO_BTN_ACCESSIBILITY_ID = "preferenceDisplayingCell_1_0"
GHA_SPEAKER_GROUP_BTN_ACCESSIBILITY_ID = "preferenceDisplayingCell_2_0"
GHA_AUTOMATION_BTN_ACCESSIBILITY_ID = "preferenceDisplayingCell_3_0"
GHA_LINK_APP_SERVICE_BTN_ACCESSIBILITY_ID = "preferenceDisplayingCell_4_0"
GHA_HOME_MEMBER_BTN_ACCESSIBILITY_ID = "preferenceDisplayingCell_5_0"
GHA_HOME_BTN_ACCESSIBILITY_ID = "preferenceDisplayingCell_6_0"
GHA_USE_PAIRING_CODE_ACCESSIBILITY_ID = "Use pairing code"
GHA_NEXT_BTN_ACCESSIBILITY_ID = "Next"
GHA_DONE_BTN_ACCESSIBILITY_ID = "Done"
GHA_OK_BTN_ACCESSIBILITY_ID = "OK"
GHA_TOGGLE_ACCESSIBILITY_ID = "preferenceToggleView"
GHA_VIDEO_HISTORY_ACCESSIBILITY_ID = "Video history"
GHA_CONNECTING_TITLE_ACCESSIBILITY_ID = "HeaderView_headlineLabel"
GHA_NO_THANKS_BTN_ACCESSIBILITY_ID = "No thanks"
GHA_ADD_AWAY_BTN_ACCESSIBILITY_ID = "Add Anyway"
GHA_CONTINUE_BTN_ACCESSIBILITY_ID = "Continue"
GHA_SET_UP_ANYWAY_BTN_ACCESSIBILITY_ID = "Set up anyway"


# CLASS NAME
GHA_TEXT_EDIT_VIEW_CLASS_NAME = "XCUIElementTypeTextField"
GHA_COMMISSION_WINDOW_TITLE = "XCUIElementTypeTextView"
GHA_COMMISSION_WINDOW_ALERT = "XCUIElementTypeAlert"

# XPATH
GHA_CONTINUE_BTN_XPATH = "//XCUIElementTypeButton[@name=\"Footer_actionBar\" and @label=\"Continue\"]"

# label
GHA_CAMERA_PLAYER_LABEL = "Camera on, viewing live stream"


SHOULD_RETRY_CONNECTING_REGEX_LIST = [
    r"Can't find device",
    r"Something went wrong",
    r"Can't connect to your device",
    r"Can't reach device",
    r"Unable to Connect to Network"
]


UNCERTIFIED_ERROR_LIST = [
    "Not a Matter-certified device",
    "Uncertified device",

]



class TAB(Enum):
    """Enumeration of GHA primary tabs."""
    HOME = "HOME"
    FAVORITES = "FAVORITES"
    DEVICES = "DEVICES"
    AUTOMATIONS = "AUTOMATIONS"
    ACTIVITY = "ACTIVITY"
    SETTINGS = "SETTINGS"
    UNKNOWN = "UNKNOWN"

class CHIP(Enum):
    """Enumeration of category chips under the Home tab."""
    FAVORITES = "Favorites"
    DEVICES = "All devices"
    CAMERAS = "Cameras"
    LIGHTS = "Lights"