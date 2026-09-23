"""Gemini AI reporter for summarizing test execution results and analyzing failure logs."""
import os
from typing import Any, Dict, List, Optional
from utils import logging_utils
from common import constants


class GeminiReporter:
    """Generates structured Markdown test reports and root cause analysis using Gemini API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "Gemini 3.8 Flash") -> None:
        """Initialize Gemini client with API key.
        Args:
            api_key (str, optional): Gemini API key. Defaults to os.environ.get('GEMINI_API_KEY').
            model (str): Gemini model name. Defaults to 'gemini-2.5-flash'.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model_name = model
        self.api_key = api_key or constants.GEMINI_API_KEY
        self.client = None
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info("Initialized Google GenAI client successfully.")
            except ImportError:
                logger.warning("google-genai package not installed. Run: pip install google-genai")
        else:
            logger.warning("GEMINI_API_KEY not set. GeminiReporter will use template-based fallback.")

    def generate_markdown_report(
            self,
            test_name: str,
            dut_name: str,
            total_runs: int,
            passed_runs: int,
            failed_runs: int,
            duration_seconds: float,
            error_message: Optional[str] = None,
            log_snippet: Optional[str] = None,
            attachment_names: Optional[List[str]] = None
    ) -> str:
        """Generate structured Markdown report via Gemini API or fallback template.
        Returns:
            str: Markdown formatted report ready to be posted to Buganizer.
        """
        pass_rate = (passed_runs / total_runs * 100) if total_runs > 0 else 0
        overall_status = "PASSED" if failed_runs == 0 and passed_runs > 0 else "FAILED"
        status_icon = "🟢" if overall_status == "PASSED" else "🔴"
        if not self.client:
            return self._build_template_report(
                test_name, dut_name, overall_status, status_icon,
                total_runs, passed_runs, failed_runs, pass_rate,
                duration_seconds, error_message, attachment_names
            )
        prompt = f"""
You are a senior QA Test Automation Engineer analyzing iOS Google Home App (iGHA) Matter device testing results.
Generate an executive, professional Markdown report formatted for Google Buganizer issue comments (similar to b/555600103).
### Test Run Metadata:
- Test Name: {test_name}
- Device Under Test (DUT): {dut_name}
- Overall Status: {overall_status}
- Iterations: Total {total_runs} (Passed: {passed_runs}, Failed: {failed_runs}, Pass Rate: {pass_rate:.1f}%)
- Total Duration: {duration_seconds:.2f}s
- Attached Artifacts: {', '.join(attachment_names or ['None'])}
### Error Details:
{error_message or 'None (All iterations passed)'}
### Recent Execution Log Snippet:
### Instructions for Report:
1. Include an executive summary at the top with status badges ({status_icon} {overall_status}).
2. Include a summary metrics table (Iterations, Pass Rate, Total Duration, DUT).
3. If FAILED, provide a dedicated "🔍 Failure & Root Cause Analysis" section detailing:
   - What step failed.
   - Likely root cause based on the error message and log snippet.
   - Recommended next actions.
4. If PASSED, provide a "✅ Milestone Execution Summary" confirming pairing, OOBE, and live video streaming stages.
5. List all uploaded log/artifact attachments at the bottom.
6. Keep the formatting clean, professional, and directly in Markdown.
"""
        try:
            logger.info("Calling Gemini API to generate intelligent Markdown report...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}. Falling back to standard template.")
            return self._build_template_report(
                test_name, dut_name, overall_status, status_icon,
                total_runs, passed_runs, failed_runs, pass_rate,
                duration_seconds, error_message, attachment_names
            )

    def _build_template_report(
            self, test_name: str, dut_name: str, status: str, icon: str,
            total: int, passed: int, failed: int, rate: float,
            duration: float, error: Optional[str], attachments: Optional[List[str]]
    ) -> str:
        """Standard Markdown template fallback when Gemini API is unavailable."""
        lines = [
            f"## {icon} [Automation Report] {test_name} - {status}",
            "",
            "### 📊 Execution Summary",
            "| Metric | Value |",
            "| :--- | :--- |",
            f"| **Device Under Test (DUT)** | `{dut_name}` |",
            f"| **Overall Status** | **{status}** |",
            f"| **Total Iterations** | {total} |",
            f"| **Passed / Failed** | {passed} / {failed} ({rate:.1f}%) |",
            f"| **Total Duration** | {duration:.2f}s |",
            "",
        ]
        if error:
            lines.extend([
                "### 🔍 Failure Details",
                "```text",
                error.strip(),
                "```",
                "",
            ])
        if attachments:
            lines.extend([
                "### 📁 Uploaded Logs & Artifacts",
                *[f"- `{name}`" for name in attachments],
                ""
            ])
        lines.append("--- \n*Generated automatically by iGHA Automation Test Runner.*")
        return "\n".join(lines)