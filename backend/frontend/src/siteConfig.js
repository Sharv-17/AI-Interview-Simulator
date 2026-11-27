// Site-wide settings. Fill in every value marked TODO before you launch.
// `npm run check:launch` fails while any TODO is left here.

export const site = {
  name: 'AI Interview Simulator',
  // Your custom domain, without https://, for example "interviewsim.in".
  domain: 'TODO_your-domain.com',
  // The person or company that runs the site (shown in the privacy policy and terms).
  operatorName: 'TODO_Your name or company name',
  contactEmail: 'TODO_contact@your-domain.com',
  // Date the current privacy policy and terms take effect, for example "1 December 2026".
  policyEffectiveDate: 'TODO_1 December 2026',
  // Courts and law that govern the terms, for example "the laws of India, courts of Pune".
  governingLaw: 'TODO_the laws of India, with courts in your city',
  // Company that runs the AI model which scores answers, as set in backend/.env (LLM_PROVIDER).
  aiProviderName: 'TODO_Anthropic',
  // Where the database is hosted, for example "Neon (PostgreSQL)".
  databaseHostName: 'TODO_Neon (PostgreSQL)',
  // How long you keep interview data, for example "12 months after the interview".
  retentionPeriod: 'TODO_12 months after the interview',
}

// Must match MAX_RECORDING_SECONDS in backend/.env (default 60).
export const MAX_RECORDING_SECONDS = 60

// Must match MAX_ANSWER_CHARS in backend/.env (default 20000).
export const MAX_ANSWER_CHARS = 20000
