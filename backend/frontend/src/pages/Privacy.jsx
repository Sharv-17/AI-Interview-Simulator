import { Link } from 'react-router-dom'
import { site } from '../siteConfig.js'
import usePageTitle from '../hooks/usePageTitle.js'

export default function Privacy() {
  usePageTitle('Privacy policy')
  return (
    <article className="container narrow section legal">
      <h1>Privacy policy</h1>
      <p className="muted">Effective {site.policyEffectiveDate}</p>

      <p>
        This policy explains what {site.name} (&quot;we&quot;, &quot;us&quot;), run by {site.operatorName}, collects
        when you use {site.domain}, why, and what you can do about it. Questions:{' '}
        <a href={`mailto:${site.contactEmail}`}>{site.contactEmail}</a>.
      </p>

      <h2>What we collect</h2>
      <p>You can use the site as a guest or with an account. Both collect the interview data below.</p>
      <ul>
        <li>
          <strong>Account details (accounts only):</strong> your full name and email address. Your password is
          never stored as written: we keep only a one-way scrambled version (an Argon2id hash) that cannot be
          turned back into the password.
        </li>
        <li>
          <strong>Interview settings:</strong> the topic, starting difficulty and number of questions you choose.
        </li>
        <li>
          <strong>Your answers:</strong> the text you submit for each question, including any voice transcript you
          chose to submit.
        </li>
        <li>
          <strong>Voice recordings:</strong> if you record an answer, the audio is sent to our server, turned into
          text, and then deleted. We do not store the audio.
        </li>
        <li>
          <strong>Scores and feedback:</strong> the score, feedback and estimated level produced for each answer.
        </li>
        <li>
          <strong>Timing:</strong> when each question started and when you submitted, measured by our server.
        </li>
        <li>
          <strong>Session notes:</strong> whether you copied or pasted in the answer box, switched tabs or left the
          window during a question, and for how long. We never read what you copied or pasted.
        </li>
        <li>
          <strong>Technical data:</strong> to stop repeated sign-in and registration attempts, our server briefly
          counts attempts per IP address and email address. Like most websites, our hosting providers may also log
          your IP address, browser type and request times to keep the service running and secure.
        </li>
      </ul>
      <p>Guests do not give us a name, email address or password. Please do not put personal information in your answers.</p>

      <h2>How we use it</h2>
      <ul>
        <li>To run your interview, choose the next question and score your answers.</li>
        <li>To show you your report and, if you have an account, your interview history and progress.</li>
        <li>To sign you in and keep your account secure.</li>
        <li>To find and fix problems and to improve the questions and scoring.</li>
      </ul>
      <p>We do not sell your data and we do not use it for advertising.</p>

      <h2>Who we share it with</h2>
      <ul>
        <li>
          <strong>{site.aiProviderName}:</strong> each question and your answer are sent to this company&apos;s AI
          model so it can score the answer. It processes them under its own terms and privacy policy.
        </li>
        <li>
          <strong>{site.databaseHostName}:</strong> stores account and interview data on our behalf.
        </li>
        <li>
          <strong>Authorities:</strong> only when the law requires it.
        </li>
      </ul>

      <h2>Who can see your report</h2>
      <p>
        <strong>Account interviews</strong> can only be opened while signed in to the account that started them.{' '}
        <strong>Guest interviews</strong> have no account behind them, so anyone who has the link to a guest interview
        or report can open it. Keep guest links private if you do not want others to see your answers.
      </p>

      <h2>What is stored on your device</h2>
      <p>
        When you sign in, we set one cookie that keeps you signed in. It is only used for that, cannot be read by
        scripts on the page, and is removed when you sign out or after 7 days. For guests, the site keeps a list of
        recent interview links in your browser&apos;s local storage so you can reopen them; you can clear it from the
        guest page or your browser settings. We do not use analytics, advertising or tracking cookies.
      </p>

      <h2>How long we keep it</h2>
      <p>We keep interview data for {site.retentionPeriod}, then delete it.</p>

      <h2>Your choices</h2>
      <p>
        You can ask us for a copy of your data, to correct it, or to delete your account and its interviews, by
        emailing <a href={`mailto:${site.contactEmail}`}>{site.contactEmail}</a> from the email address on your account.
        For a guest interview, include its link. We will reply within 30 days.
      </p>

      <h2>Age</h2>
      <p>This service is intended for people aged 18 or older.</p>

      <h2>Changes</h2>
      <p>
        If we change this policy we will update the date at the top of this page. Significant changes will also be
        noted on the home page.
      </p>

      <p><Link to="/terms">Read the terms and conditions</Link></p>
    </article>
  )
}
