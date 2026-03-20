"""Quick test: append a row to Google Sheets and verify placement."""

from dotenv import load_dotenv
load_dotenv()

from jobseeker.google_tools import log_application_to_sheets

result = log_application_to_sheets(
    job_link="https://example.com/test-job",
    company="Test Company",
    position="Test Engineer",
    cv_url="https://drive.google.com/file/d/test/view",
)
print(result)
