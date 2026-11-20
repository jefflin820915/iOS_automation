"""Page object for AT&T Connected Life Camera Live Stream verification and navigation back."""

from dataclasses import dataclass
import io
import math
import struct
import time
from typing import Any, Dict, List, Optional, Tuple
import zlib
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException

from common import constants
from common.base_page import BasePage
from page_object.Partner.ATT.att_common import (
    ATTBasePage,
    IOS_PREDICATE_BY,
)
from utils import logging_utils


@dataclass
class _ATTLiveSample:
    t: float
    is_live: bool
    top_left_status: str = ""
    has_video: Optional[bool] = None
    video_detail: str = ""
    detail: str = ""


class ATTCameraLivePage(ATTBasePage):
    """Waits for top-left `'Live'` indicator, verifies stability for 5~10s, and navigates back."""

    DEFAULT_WAIT_LIVE_TIMEOUT_S: float = 30.0
    DEFAULT_VERIFY_DURATION_S: float = 8.0  # within 5~10s window requested
    DEFAULT_CHECK_INTERVAL_S: float = 1.0

    TOP_LEFT_LIVE_PREDICATE: str = (
        'type == "XCUIElementTypeStaticText" AND '
        '(name == "Live" OR label == "Live" OR value == "Live")'
    )

    PLAYER_ERROR_PREDICATE: str = (
        'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeAlert"} AND ('
        'label CONTAINS[c] "Unable to play" '
        'OR label CONTAINS[c] "camera is offline" '
        'OR label CONTAINS[c] "device is offline" '
        'OR label CONTAINS[c] "connection failed" '
        'OR label CONTAINS[c] "failed to load")'
    )

    BACK_TO_ROOM_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND name == "BackButton"'
    )

    ROOM_SETTINGS_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "group_settings_navbar_button" OR label == "Room Settings")'
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "att_camera_live")

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "ATTCameraLivePage":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "attcameralivepage", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(getattr(session, "attcameralivepage", None), cls):
            return session.attcameralivepage
        page = cls(ctx.driver)
        if session is not None:
            page.session = session
        return page

    def _is_app_in_foreground(self) -> bool:
        bundle_id = self._att_bundle_id()
        fg_state = getattr(constants, "APP_STATE_FOREGROUND", 4)
        try:
            if hasattr(self.driver, "query_app_state"):
                return self.driver.query_app_state(bundle_id) == fg_state
        except WebDriverException:
            return False
        return True

    def _probe_top_left_status(self) -> Tuple[bool, str, str]:
        """Inspect top-left player badge and player errors.

        Returns:
            (is_live, top_left_status, detail)
            - `top_left_status` is e.g. `'Live'`, `'Connecting'`, `'Offline'`,
              `'Error: ...'`, `'Loading (spinner)'`, or `'No top-left status badge'`.
        """
        win_w, win_h = self._att_window_size()
        min_badge_y = int(win_h * 0.105)  # strictly below top NavigationBar (~88pt on 844pt screen)
        max_y = int(win_h * 0.38)
        max_badge_y = int(win_h * 0.28)
        max_x = int(win_w * 0.60)
        with self._att_fast_probe():
            try:
                candidates = self.driver.find_elements(IOS_PREDICATE_BY,
                                                       self.TOP_LEFT_LIVE_PREDICATE)
            except WebDriverException as err:
                err_txt = f"probe_error:{str(err)[:60]}"
                return False, err_txt, err_txt

            for el in candidates:
                if not self._att_is_element_on_screen(el, require_visible_attr=True):
                    continue
                txt = self._att_read_attr(el, ("value", "label", "name"))
                # Strict Title Case check avoids lower timeline header `"LIVE"`
                if txt != "Live":
                    continue
                try:
                    rect = el.rect or {}
                except WebDriverException:
                    continue
                if rect.get("y", win_h) <= max_y and rect.get("x", win_w) <= max_x:
                    return True, "Live", f"Live@({rect.get('x')},{rect.get('y')})"

            try:
                for err_el in self.driver.find_elements(IOS_PREDICATE_BY,
                                                        self.PLAYER_ERROR_PREDICATE):
                    if self._att_is_element_on_screen(err_el, require_visible_attr=True):
                        err_msg = self._att_read_attr(err_el)[:60]
                        return False, f"Error: {err_msg}", f"error:{err_msg}"
            except WebDriverException:
                pass

            # Look for non-'Live' status text in the player's top-left pill (e.g. Connecting / Loading / Offline)
            try:
                badge_texts: List[Tuple[int, str]] = []
                for st in self.driver.find_elements(AppiumBy.CLASS_NAME,
                                                    "XCUIElementTypeStaticText"):
                    if not self._att_is_element_on_screen(st, require_visible_attr=True):
                        continue
                    try:
                        r = st.rect or {}
                    except WebDriverException:
                        continue
                    ry = r.get("y", win_h)
                    rx = r.get("x", win_w)
                    if min_badge_y <= ry <= max_badge_y and rx <= int(win_w * 0.55):
                        txt = self._att_read_attr(st, ("value", "label", "name"))
                        if txt and txt.upper() != "LIVE":
                            badge_texts.append((int(ry), txt))
                if badge_texts:
                    badge_texts.sort(key=lambda item: item[0])
                    status_txt = badge_texts[0][1][:60]
                    return False, status_txt, status_txt
            except WebDriverException:
                pass

            try:
                for sp in self.driver.find_elements(AppiumBy.CLASS_NAME,
                                                    "XCUIElementTypeActivityIndicator"):
                    if not self._att_is_element_on_screen(sp, require_visible_attr=True):
                        continue
                    r = getattr(sp, "rect", None) or {}
                    if min_badge_y <= r.get("y", win_h) <= int(win_h * 0.40):
                        return False, "Loading (spinner)", "Loading (spinner)"
            except WebDriverException:
                pass

        return False, "No top-left status badge", "waiting_for_live"

    def _has_top_left_live_indicator(self) -> Tuple[bool, str]:
        """Detect top-left player badge `Live` (`x=68, y=119`, distinct from timeline `'LIVE'`)."""
        is_live, _status, detail = self._probe_top_left_status()
        return is_live, detail

    def _find_player_rect(self, win_w: int, win_h: int) -> Dict[str, float]:
        """Locate the AT&T video player bounding rect in points (falling back to verified 16:9 area)."""
        min_y = int(win_h * 0.08)
        max_y = int(win_h * 0.22)
        min_w = int(win_w * 0.80)
        min_h = int(win_h * 0.16)
        max_h = int(win_h * 0.36)
        with self._att_fast_probe():
            for cls_name in ("XCUIElementTypeImage", "XCUIElementTypeOther"):
                try:
                    elems = self.driver.find_elements(AppiumBy.CLASS_NAME, cls_name)
                except WebDriverException:
                    continue
                for el in elems:
                    try:
                        r = el.rect or {}
                    except WebDriverException:
                        continue
                    rw = float(r.get("width", 0) or 0)
                    rh = float(r.get("height", 0) or 0)
                    ry = float(r.get("y", -1) or -1)
                    if rw >= min_w and min_h <= rh <= max_h and min_y <= ry <= max_y:
                        return {"x": float(r.get("x", 0) or 0), "y": ry, "width": rw, "height": rh}
        return {
            "x": 0.0,
            "y": float(int(win_h * 0.125)),
            "width": float(win_w),
            "height": float(int(win_h * 0.255)),
        }

    @staticmethod
    def _decode_png_crop_rgb_grid(
            png_bytes: bytes, x0: int, y0: int, x1: int, y1: int, grid_cols: int = 32,
            grid_rows: int = 16
    ) -> Tuple[int, int, List[List[Tuple[int, int, int]]]]:
        """Decode the target crop of a PNG into a sampled RGB grid (PIL fast-path with pure-Python fallback)."""
        try:
            from PIL import Image  # type: ignore

            with Image.open(io.BytesIO(png_bytes)) as img:
                rgb_img = img.convert("RGB")
                width, height = rgb_img.size
                cx0 = max(0, min(width - 1, x0))
                cx1 = max(cx0 + 1, min(width, x1))
                cy0 = max(0, min(height - 1, y0))
                cy1 = max(cy0 + 1, min(height, y1))
                step_x = max(1, (cx1 - cx0) // grid_cols)
                step_y = max(1, (cy1 - cy0) // grid_rows)
                pixels = rgb_img.load()
                grid: List[List[Tuple[int, int, int]]] = []
                for row in range(cy0, cy1, step_y):
                    row_vals: List[Tuple[int, int, int]] = []
                    for col in range(cx0, cx1, step_x):
                        r, g, b = pixels[col, row][:3]
                        row_vals.append((int(r), int(g), int(b)))
                    if row_vals:
                        grid.append(row_vals)
                return width, height, grid
        except ImportError:
            pass

        if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Screenshot payload is not a valid PNG")
        pos = 8
        width = height = bit_depth = color_type = interlace = 0
        idat_chunks: List[bytes] = []
        while pos + 8 <= len(png_bytes):
            length, ctype = struct.unpack(">I4s", png_bytes[pos: pos + 8])
            data = png_bytes[pos + 8: pos + 8 + length]
            pos += 12 + length
            if ctype == b"IHDR":
                width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB",
                                                                                      data)
            elif ctype == b"IDAT":
                idat_chunks.append(data)
            elif ctype == b"IEND":
                break
        if width <= 0 or height <= 0 or bit_depth != 8 or interlace != 0 or color_type not in (0, 2,
                                                                                               4,
                                                                                               6):
            raise ValueError(
                f"Unsupported PNG header: {width}x{height} bit_depth={bit_depth} color={color_type} interlace={interlace}"
            )
        bpp = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
        raw = zlib.decompress(b"".join(idat_chunks))
        stride = width * bpp
        cx0 = max(0, min(width - 1, x0))
        cx1 = max(cx0 + 1, min(width, x1))
        cy0 = max(0, min(height - 1, y0))
        cy1 = max(cy0 + 1, min(height, y1))
        step_x = max(1, (cx1 - cx0) // grid_cols)
        step_y = max(1, (cy1 - cy0) // grid_rows)

        prev = bytearray(stride)
        grid = []
        offset = 0
        for row in range(cy1):
            ftype = raw[offset]
            offset += 1
            cur = bytearray(raw[offset: offset + stride])
            offset += stride
            if ftype == 1:
                for i in range(bpp, stride):
                    cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
            elif ftype == 2:
                for i in range(stride):
                    cur[i] = (cur[i] + prev[i]) & 0xFF
            elif ftype == 3:
                for i in range(bpp):
                    cur[i] = (cur[i] + (prev[i] >> 1)) & 0xFF
                for i in range(bpp, stride):
                    cur[i] = (cur[i] + ((cur[i - bpp] + prev[i]) >> 1)) & 0xFF
            elif ftype == 4:
                for i in range(bpp):
                    cur[i] = (cur[i] + prev[i]) & 0xFF
                for i in range(bpp, stride):
                    a = cur[i - bpp]
                    b = prev[i]
                    c = prev[i - bpp]
                    p = a + b - c
                    pa = abs(p - a)
                    pb = abs(p - b)
                    pc = abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    cur[i] = (cur[i] + pr) & 0xFF
            if row >= cy0 and ((row - cy0) % step_y == 0):
                row_vals = []
                for col in range(cx0, cx1, step_x):
                    idx = col * bpp
                    if color_type in (2, 6):
                        row_vals.append((cur[idx], cur[idx + 1], cur[idx + 2]))
                    else:
                        v = cur[idx]
                        row_vals.append((v, v, v))
                if row_vals:
                    grid.append(row_vals)
            prev = cur
        return width, height, grid

    @classmethod
    def analyze_player_video_grid(
            cls, grid: List[List[Tuple[int, int, int]]]
    ) -> Tuple[bool, str]:
        """Classify a sampled player RGB grid as real video (`True`) vs black/blank/spinner (`False`).

        Evaluates luminance and color variation on the outer 72% perimeter outside the dead-center
        overlay box so a white loading spinner or centered error text on a black/gray background
        still detects as NO video image.
        """
        rows = len(grid)
        cols = len(grid[0]) if rows else 0
        if rows < 3 or cols < 3:
            return False, "empty_crop"

        all_rgb: List[Tuple[int, int, int]] = []
        edge_rgb: List[Tuple[int, int, int]] = []
        for r_idx, row in enumerate(grid):
            ry = r_idx / float(max(1, rows - 1))
            for c_idx, px in enumerate(row):
                rx = c_idx / float(max(1, cols - 1))
                all_rgb.append(px)
                in_center = (0.28 <= rx <= 0.72) and (0.14 <= ry <= 0.76)
                if not in_center:
                    edge_rgb.append(px)

        target_rgb = edge_rgb if len(edge_rgb) >= 12 else all_rgb
        lumas = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in target_rgb]
        n = len(lumas)
        mean_l = sum(lumas) / n
        std_l = math.sqrt(sum((v - mean_l) ** 2 for v in lumas) / n)
        sorted_l = sorted(lumas)
        p05 = sorted_l[max(0, int(0.05 * (n - 1)))]
        p25 = sorted_l[max(0, int(0.25 * (n - 1)))]
        p75 = sorted_l[min(n - 1, int(0.75 * (n - 1)))]
        p95 = sorted_l[min(n - 1, int(0.95 * (n - 1)))]
        iqr_l = p75 - p25
        dyn_range = p95 - p05

        med_r = sorted(px[0] for px in target_rgb)[n // 2]
        med_g = sorted(px[1] for px in target_rgb)[n // 2]
        med_b = sorted(px[2] for px in target_rgb)[n // 2]
        non_bg = sum(
            1
            for r, g, b in target_rgb
            if max(abs(r - med_r), abs(g - med_g), abs(b - med_b)) > 14
        ) / float(n)

        stats = f"mean={mean_l:.1f},std={std_l:.1f},iqr={iqr_l:.1f},range={dyn_range:.1f},non_bg={non_bg * 100:.0f}%"
        if p95 < 18.0 and std_l < 5.0 and dyn_range < 14.0:
            return False, f"black_screen({stats})"
        if non_bg < 0.08 and iqr_l < 6.0:
            if mean_l < 24.0:
                return False, f"black_with_overlay({stats})"
            return False, f"blank_or_uniform({stats})"
        if std_l < 4.5 and dyn_range < 14.0 and non_bg < 0.08:
            return False, f"blank_or_uniform({stats})"
        return True, f"video_ok({stats})"

    def _has_player_video_image(self) -> Tuple[Optional[bool], str]:
        """Take a screenshot and verify whether the AT&T player viewport displays a real video image.

        Returns:
            (True, detail)  -> real textured video frame detected inside player viewport.
            (False, detail) -> black/blank/uniform screen (no video image), or screenshot failed.
            (None, detail)  -> driver does not expose screenshot bytes API (mock driver only).
        """
        if not hasattr(self.driver, "get_screenshot_as_png") and not hasattr(
                self.driver, "get_screenshot_as_base64"
        ):
            return None, "screenshot_unavailable"

        png_bytes: Optional[bytes] = None
        try:
            if hasattr(self.driver, "get_screenshot_as_png"):
                png_bytes = self.driver.get_screenshot_as_png()
            elif hasattr(self.driver, "get_screenshot_as_base64"):
                import base64

                b64 = self.driver.get_screenshot_as_base64()
                png_bytes = base64.b64decode(b64) if b64 else None
        except Exception as err:
            return False, f"screenshot_error:{str(err)[:60]}"

        if not png_bytes:
            return False, "empty_screenshot"

        win_w, win_h = self._att_window_size()
        player_rect = self._find_player_rect(win_w, win_h)
        try:
            # Read IHDR width/height quickly so we scale point rects to physical PNG pixels
            if png_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(png_bytes) >= 24:
                img_w, img_h = struct.unpack(">II", png_bytes[16:24])
            else:
                img_w, img_h = win_w, win_h
            scale_x = img_w / float(max(1, win_w))
            scale_y = img_h / float(max(1, win_h))

            # Inner video crop avoids the top-left 'Live' badge, top-right 'Nest' logo, and borders
            crop_x0 = int((player_rect["x"] + player_rect["width"] * 0.08) * scale_x)
            crop_x1 = int((player_rect["x"] + player_rect["width"] * 0.92) * scale_x)
            crop_y0 = int((player_rect["y"] + player_rect["height"] * 0.24) * scale_y)
            crop_y1 = int((player_rect["y"] + player_rect["height"] * 0.88) * scale_y)

            _, _, grid = self._decode_png_crop_rgb_grid(png_bytes, crop_x0, crop_y0, crop_x1,
                                                        crop_y1)
            return self.analyze_player_video_grid(grid)
        except Exception as err:
            return False, f"image_decode_error:{str(err)[:60]}"

    @staticmethod
    def _format_video_label(has_video: Optional[bool], video_detail: str) -> str:
        if has_video is True:
            return f"Has video ({video_detail})"
        if has_video is False:
            return f"No video ({video_detail})"
        return f"Unknown ({video_detail})"

    def wait_and_verify_live_stream(
            self,
            device_name: Optional[str] = None,
            wait_live_timeout_s: Optional[float] = None,
            verify_duration_s: Optional[float] = None,
            check_interval_s: Optional[float] = None,
    ) -> bool:
        """Step 3b: Wait for top-left `'Live'` text, verify Live + player video image for 5~10s."""
        page = ATTCameraLivePage._resolve_page(self)
        target_dev = str(device_name or getattr(self, "device_name", "") or "").strip()
        wait_timeout = float(
            wait_live_timeout_s
            if wait_live_timeout_s is not None
            else getattr(constants, "ATT_LIVE_WAIT_TIMEOUT_S", page.DEFAULT_WAIT_LIVE_TIMEOUT_S)
        )
        duration = float(
            verify_duration_s
            if verify_duration_s is not None
            else getattr(constants, "ATT_LIVE_VERIFY_SECONDS", page.DEFAULT_VERIFY_DURATION_S)
        )
        interval = float(
            check_interval_s
            if check_interval_s is not None
            else getattr(constants, "ATT_LIVE_CHECK_INTERVAL_S", page.DEFAULT_CHECK_INTERVAL_S)
        )
        dev_status = getattr(getattr(page, "session", None), "last_device_status", None) or getattr(
            page.driver, "_att_device_status", "Unknown"
        )

        # Wait for any blocking iOS top notification banner to disappear before inspecting Live UI
        page._wait_until_top_notification_disappears(force=True)

        # Phase A: Wait up to wait_timeout for top-left 'Live' badge to appear
        page._logger.info(
            f"[ATT Live] Waiting up to {wait_timeout:.0f}s for top-left 'Live' indicator "
            f"(device='{target_dev}', device_status='{dev_status}')..."
        )
        wait_start = time.time()
        last_top_left_status = "No top-left status badge"
        reached_live = False
        while (time.time() - wait_start) < wait_timeout:
            if not page._is_app_in_foreground():
                last_top_left_status = "app_not_foreground"
                break
            is_live, top_left_status, detail = page._probe_top_left_status()
            last_top_left_status = top_left_status
            if is_live:
                reached_live = True
                page._logger.info(
                    f"[ATT Live] Top-left 'Live' appeared after {time.time() - wait_start:.1f}s ({detail}). "
                    f"Starting {duration:.0f}s live & player video image verification..."
                )
                break
            t_notif_before = time.time()
            _cleared, notif_waited = page._wait_until_top_notification_disappears_timed()
            if notif_waited > 0:
                wait_start += max(0.0, time.time() - t_notif_before)
                continue
            time.sleep(0.5)

        if not reached_live and page._is_app_in_foreground():
            _cleared, notif_waited = page._wait_until_top_notification_disappears_timed(force=True)
            if notif_waited > 0:
                is_live, top_left_status, detail = page._probe_top_left_status()
                last_top_left_status = top_left_status
                if is_live:
                    reached_live = True
                    page._logger.info(
                        f"[ATT Live] Top-left 'Live' visible after top notification cleared ({detail}). "
                        f"Starting {duration:.0f}s live & player video image verification..."
                    )

        if not reached_live:
            has_video, video_detail = (
                page._has_player_video_image()
                if page._is_app_in_foreground()
                else (False, "app_not_foreground")
            )
            video_str = page._format_video_label(has_video, video_detail)
            msg = (
                f"[NEVER_LIVE] AT&T Camera '{target_dev}' (room_status='{dev_status}') "
                f"did not show top-left 'Live' within {wait_timeout:.0f}s | "
                f"Player Video: {video_str} | "
                f"Last Top-Left Live Status: '{last_top_left_status}'."
            )
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        # Phase B: Verify top-left 'Live' AND real video image remain active for 5~10s
        samples: List[_ATTLiveSample] = []
        verify_start = time.time()
        while (time.time() - verify_start) < duration:
            iter_start = time.time()
            elapsed = iter_start - verify_start
            if not page._is_app_in_foreground():
                samples.append(
                    _ATTLiveSample(
                        elapsed,
                        False,
                        top_left_status="app_not_foreground",
                        has_video=False,
                        video_detail="app_not_foreground",
                        detail="app_not_foreground",
                    )
                )
                break
            is_live, top_left_status, detail = page._probe_top_left_status()
            has_video, video_detail = page._has_player_video_image()
            if not is_live or has_video is False:
                t_notif_before = time.time()
                _cleared, notif_waited = page._wait_until_top_notification_disappears_timed()
                if notif_waited > 0:
                    verify_start += max(0.0, time.time() - t_notif_before)
                    is_live, top_left_status, detail = page._probe_top_left_status()
                    has_video, video_detail = page._has_player_video_image()
            samples.append(
                _ATTLiveSample(
                    elapsed,
                    is_live,
                    top_left_status=top_left_status,
                    has_video=has_video,
                    video_detail=video_detail,
                    detail=detail,
                )
            )
            if is_live and has_video is not False:
                page._logger.info(
                    f"[ATT Live] Streaming smoothly ({elapsed:.1f}s / {duration:.0f}s | "
                    f"{detail} | video={video_detail})"
                )
            elif is_live and has_video is False:
                page._logger.warning(
                    f"[ATT Live] Top-left 'Live' visible at {elapsed:.1f}s, "
                    f"but NO video image in player ({video_detail})"
                )
            else:
                page._logger.warning(
                    f"[ATT Live] Top-left status='{top_left_status}' at {elapsed:.1f}s | video={video_detail}"
                )
            probe_cost = time.time() - iter_start
            remaining = duration - (time.time() - verify_start)
            sleep_for = min(max(0.0, interval - probe_cost), max(0.0, remaining))
            if sleep_for > 0:
                time.sleep(sleep_for)

        if page._is_app_in_foreground():
            t_notif_before = time.time()
            _cleared, notif_waited = page._wait_until_top_notification_disappears_timed(force=True)
            if notif_waited > 0:
                verify_start += max(0.0, time.time() - t_notif_before)
            final_live, final_top_left, final_detail = page._probe_top_left_status()
            final_video, final_video_detail = page._has_player_video_image()
        else:
            final_live, final_top_left, final_detail = False, "app_not_foreground", "app_not_foreground"
            final_video, final_video_detail = False, "app_not_foreground"

        samples.append(
            _ATTLiveSample(
                time.time() - verify_start,
                final_live,
                top_left_status=final_top_left,
                has_video=final_video,
                video_detail=final_video_detail,
                detail=final_detail,
            )
        )

        non_live_count = sum(1 for s in samples if not s.is_live)
        live_count = sum(1 for s in samples if s.is_live)
        video_checked = any(s.has_video is not None for s in samples)
        video_ok_count = sum(1 for s in samples if s.has_video is True)
        final_video_ok = final_video is not False
        video_str = page._format_video_label(final_video, final_video_detail)

        if not final_live or live_count == 0:
            timeline_str = " -> ".join(
                f"{s.t:.1f}s:{s.top_left_status or s.detail}"
                f"({'video' if s.has_video else ('no_video' if s.has_video is False else 'n/a')})"
                for s in samples[:10]
            )
            msg = (
                f"[NOT_LIVE_AT_END] AT&T Camera '{target_dev}' dropped top-left 'Live' during "
                f"{duration:.0f}s check (live_samples={live_count}/{len(samples)}, "
                f"video_samples={video_ok_count}/{len(samples)}) | "
                f"Player Video: {video_str} | "
                f"Last Top-Left Live Status: '{final_top_left}'. "
                f"Timeline: {timeline_str}"
            )
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        if not final_video_ok or (video_checked and video_ok_count == 0):
            timeline_str = " -> ".join(
                f"{s.t:.1f}s:{s.top_left_status}({'video' if s.has_video else 'no_video'})"
                for s in samples[:10]
            )
            msg = (
                f"[NO_VIDEO_IMAGE] AT&T Camera '{target_dev}' showed top-left '{final_top_left}' "
                f"but player had NO video image (live_samples={live_count}/{len(samples)}, "
                f"video_samples={video_ok_count}/{len(samples)}) | "
                f"Player Video: {video_str} | "
                f"Last Top-Left Live Status: '{final_top_left}'. "
                f"Timeline: {timeline_str}"
            )
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        page._logger.info(
            f"[ATT Live] SUCCESS: Top-left 'Live' & player video image verified for "
            f"{time.time() - verify_start:.1f}s (live_samples={live_count}/{len(samples)}, "
            f"video_samples={video_ok_count}/{len(samples)}, non_live={non_live_count}, "
            f"video={final_video_detail})."
        )
        return True

    def click_back_to_room(
            self, room_name: Optional[str] = None, timeout: float = 8.0
    ) -> bool:
        """Step 4 (1st Back): Click top-left BackButton (`label='<room_name>'`) -> return to Room page."""
        page = ATTCameraLivePage._resolve_page(self)
        target_room = str(room_name or getattr(self, "room_name", "Attic") or "Attic").strip()
        win_w, _ = page._att_window_size()

        for attempt in range(1, 3):
            page._wait_until_top_notification_disappears(force=True)
            back_btn: Optional[WebElement] = None
            with page._att_fast_probe():
                try:
                    for b in page.driver.find_elements(IOS_PREDICATE_BY,
                                                       page.BACK_TO_ROOM_BTN_PREDICATE):
                        rect = getattr(b, "rect", None) or {}
                        if (
                                page._att_is_element_on_screen(b)
                                and rect.get("y", 0) < 140
                                and rect.get("x", 0) < int(win_w * 0.40)
                        ):
                            back_btn = b
                            break
                except WebDriverException:
                    back_btn = None

            if back_btn is not None:
                page._logger.info(
                    f"[ATT Live] Clicking BackButton (label='{target_room}', attempt {attempt}/2) "
                    "to return to Room page..."
                )
                page._att_tap_element_or_coords(
                    back_btn,
                    desc=f"Live BackButton -> {target_room}",
                    prefer_coords=(attempt > 1),
                )
            else:
                page._wait_until_top_notification_disappears(force=True)
                page._logger.info(
                    f"[ATT Live] BackButton not found via query; tapping top-left nav fallback (attempt {attempt}/2)..."
                )
                try:
                    page.driver.execute_script("mobile: tap", {"x": 38, "y": 69})
                except WebDriverException:
                    pass

            deadline = time.time() + min(timeout, 5.0)
            while time.time() < deadline:
                with page._att_fast_probe():
                    try:
                        in_room = any(
                            page._att_is_element_on_screen(e)
                            for e in page.driver.find_elements(
                                IOS_PREDICATE_BY,
                                'name == "group_settings_navbar_button" OR '
                                '(name == "BackButton" AND label == "Devices")',
                            )
                        )
                    except WebDriverException:
                        in_room = False
                if in_room:
                    page._logger.info(f"[ATT Live] Returned to Room page '{target_room}'.")
                    return True
                time.sleep(0.4)

        msg = f"Failed to navigate back from Live Stream to Room page '{target_room}'."
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
        raise AssertionError(msg)
