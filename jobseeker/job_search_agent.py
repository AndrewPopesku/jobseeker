from google.adk.agents.llm_agent import LlmAgent
from jobseeker.tools import search_indeed_jobs, search_linkedin_jobs, get_job_description

job_search_agent = LlmAgent(
    model="gemini-3-flash-preview",
    name="job_search_agent",
    description=(
        "Searches for job listings on Indeed and LinkedIn, and retrieves full job descriptions. "
        "Use this agent when the user wants to find jobs, search for positions, or get details about a specific job posting."
    ),
    instruction=(
        "You are a job search specialist. Search Indeed and LinkedIn based on the user's query and location. "
        "Retrieve full job descriptions when requested — return the full text for CV tailoring.\n\n"
        "Return results as plain text only. Never use **, *, #, or any markdown. Format each job exactly as:\n"
        "1. Job Title\n"
        "   Company: ...\n"
        "   Location: ...\n"
        "   Posted: ...\n"
        "   View job: <url>"
    ),
    tools=[search_indeed_jobs, search_linkedin_jobs, get_job_description],
)
