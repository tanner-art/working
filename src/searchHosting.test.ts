import { expect, it } from 'vitest'
import config from '../vercel.json'

it('serves the app shell for direct and reloaded global Search URLs', () => {
  expect(config.rewrites).toContainEqual({ source: '/search', destination: '/index.html' })
})
