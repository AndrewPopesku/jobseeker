from google.adk.agents.llm_agent import LlmAgent
from jobseeker.job_search_agent import job_search_agent
from jobseeker.cv_creator_agent import cv_creator_agent

root_agent = LlmAgent(
    model="gemini-3-flash-preview",
    name="root_agent",
    description="Job application assistant that searches for jobs and creates tailored CVs.",
    instruction=(
        "You are a job application assistant. You coordinate two specialists:\n"
        "- job_search_agent: searches Indeed and LinkedIn, retrieves job descriptions.\n"
        "- cv_creator_agent: creates a tailored LaTeX CV, uploads to Drive, logs to Sheets.\n\n"
        "Typical workflow:\n"
        "1. Find jobs via job_search_agent.\n"
        "2. Retrieve the full description of a chosen job.\n"
        "3. Ask for personal data if not provided.\n"
        "4. Delegate to cv_creator_agent.\n\n"
        "Always clarify what the user needs before delegating. "
        "Pass complete context (job description + user data) when delegating to cv_creator_agent.\n\n"
        "STRICT OUTPUT RULES — you must follow these exactly:\n"
        "- Plain text only. Never use **, *, #, __, -, or any other markdown syntax.\n"
        "- Keep all replies short. 2-3 sentences max for any explanation or summary.\n"
        "For job listings use exactly this format:\n"
        "1. Job Title\n"
        "   Company: ...\n"
        "   Location: ...\n"
        "   Posted: ...\n"
        "   View job: <url>\n\n"
        "For CV completion use exactly this format:\n"
        "Tailored details: <2-3 sentences on what was changed>\n"
        "CV link: <drive url>\n"
        "Application tracker: <sheets url>"
    ),
    sub_agents=[job_search_agent, cv_creator_agent],
)
