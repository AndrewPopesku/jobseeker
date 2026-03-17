from google.adk.agents.llm_agent import LlmAgent
from jobseeker.job_search_agent import job_search_agent
from jobseeker.cv_creator_agent import cv_creator_agent

root_agent = LlmAgent(
    model="gemini-3-flash-preview",
    name="root_agent",
    description="Job application assistant that searches for jobs and creates tailored CVs.",
    instruction=(
        "You are a job application assistant. You coordinate two specialists:\n\n"
        "- **job_search_agent**: searches Indeed and LinkedIn for job listings and retrieves full job descriptions.\n"
        "- **cv_creator_agent**: takes the user's personal data and a job description to create a tailored LaTeX CV compiled to PDF.\n\n"
        "Typical workflow:\n"
        "1. Help the user find relevant jobs using job_search_agent.\n"
        "2. Retrieve the full description of a chosen job.\n"
        "3. Ask the user for their personal data if not already provided.\n"
        "4. Delegate to cv_creator_agent to produce a tailored CV PDF.\n\n"
        "Always clarify what the user needs before delegating. "
        "Pass complete context (job description + user data) when delegating to cv_creator_agent."
    ),
    sub_agents=[job_search_agent, cv_creator_agent],
)
