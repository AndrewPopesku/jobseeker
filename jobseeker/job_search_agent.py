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
        "You are a job search specialist. Use the available tools to:\n"
        "1. Search for jobs on Indeed and/or LinkedIn based on the user's query and location.\n"
        "2. Retrieve full job descriptions from job posting URLs when requested.\n"
        "Present results in a clean, readable format. Include title, company, location, and URL. "
        "When fetching a job description, return the full text so it can be used for CV tailoring."
    ),
    tools=[search_indeed_jobs, search_linkedin_jobs, get_job_description],
)
