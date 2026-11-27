/**
 * Response-shape guards.
 *
 * A successful request that does not return the documented shape is a failure,
 * not an empty list. `expectArray` / `expectObject` throw a status-less error so
 * the page reports "unexpected response" and offers Retry.
 *
 * `asArray` is only for optional display fields inside an otherwise valid
 * record (scopes, tags, nested lists) where a missing array must not crash a
 * render. Never use it to normalise a whole list response.
 */
export class ResponseShapeError extends Error {
  constructor(label) {
    super(`The server returned an unexpected response when loading ${label}.`);
    this.name = 'ResponseShapeError';
  }
}

export function expectArray(data, label = 'this list') {
  if (!Array.isArray(data)) throw new ResponseShapeError(label);
  return data;
}

export function expectObject(data, label = 'this record') {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new ResponseShapeError(label);
  }
  return data;
}

export function asArray(value) {
  return Array.isArray(value) ? value : [];
}
