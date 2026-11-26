import { useEffect } from 'react'
import { site } from '../siteConfig.js'

export default function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} | ${site.name}` : site.name
  }, [title])
}
