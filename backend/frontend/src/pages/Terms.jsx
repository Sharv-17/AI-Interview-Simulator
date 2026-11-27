import { Link } from 'react-router-dom'
import { site } from '../siteConfig.js'
import usePageTitle from '../hooks/usePageTitle.js'

export default function Terms() {
  usePageTitle('Terms and conditions')
  return (
    <article className="container narrow section legal">
      <h1>Terms and conditions</h1>
      <p className="muted">Effective {site.policyEffectiveDate}</p>

      <p>
        These terms apply to your use of {site.name} at {site.domain}, run by {site.operatorName}. By using the site you
        agree to them. If you do not agree, please do not use it.
      </p>

      <h2>What the service is</h2>
      <p>
        {site.name} is a practice tool. It asks you technical interview questions and gives each answer a score and
        feedback produced by an AI model.
      </p>

      <h2>Scores are estimates</h2>
      <p>
        Scores, feedback and estimated levels are generated automatically and can be wrong or incomplete. They are not
        a professional assessment, a certification, or a prediction of how you will do in a real interview, and they
        must not be used to make hiring or admission decisions about anyone.
      </p>

      <h2>Accounts</h2>
      <p>
        You can practise as a guest or create an account. If you create one, give your real name and an email address
        you control, keep your password private, and tell us at{' '}
        <a href={`mailto:${site.contactEmail}`}>{site.contactEmail}</a> if you think someone else has used your account.
        You are responsible for what happens under your account. You can ask us to delete it at any time.
      </p>

      <h2>Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>break the law or infringe anyone&apos;s rights while using the service;</li>
        <li>submit content that is abusive, hateful, sexual, or contains other people&apos;s personal information;</li>
        <li>try to disrupt, overload, probe or gain unauthorised access to the service or its servers;</li>
        <li>use bots or scripts to start interviews or collect the question bank in bulk;</li>
        <li>open or share other people&apos;s interview reports without their permission.</li>
      </ul>
      <p>We may block access for anyone who breaks these rules.</p>

      <h2>Your content</h2>
      <p>
        You keep ownership of the answers you submit. You allow us to store and process them, and to send them to our
        AI provider, so we can run the service and improve it, as described in our{' '}
        <Link to="/privacy">privacy policy</Link>.
      </p>

      <h2>Our content</h2>
      <p>
        The questions, software and design of the site belong to {site.operatorName} or its licensors. You may use them
        for your own practice, but not copy or republish them in bulk.
      </p>

      <h2>Availability</h2>
      <p>
        The service is provided free of charge and may change, pause or stop at any time. Interviews in progress may be
        lost if the service is interrupted.
      </p>

      <h2>No warranty</h2>
      <p>
        The service is provided &quot;as is&quot;, without warranties of any kind, to the extent the law allows.
      </p>

      <h2>Limitation of liability</h2>
      <p>
        To the extent the law allows, {site.operatorName} is not liable for any indirect or consequential loss, or for
        decisions you make based on scores or feedback from the service. Nothing in these terms limits liability that
        cannot be limited by law.
      </p>

      <h2>Governing law</h2>
      <p>These terms are governed by {site.governingLaw}.</p>

      <h2>Changes</h2>
      <p>
        We may update these terms. The date at the top shows when they last changed. Continuing to use the site after a
        change means you accept the new terms.
      </p>

      <h2>Contact</h2>
      <p>
        <a href={`mailto:${site.contactEmail}`}>{site.contactEmail}</a>
      </p>
    </article>
  )
}
