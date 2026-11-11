import { urlAbsoluta } from '@/lib/format'

export default function robots() {
  return {
    rules: [{ userAgent: '*', allow: '/', disallow: ['/api/'] }],
    sitemap: urlAbsoluta('/sitemap.xml'),
  }
}
