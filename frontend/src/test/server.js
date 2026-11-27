import { setupServer } from 'msw/node';

// Shared API-boundary mock. Tests add handlers per case; nothing here pretends
// to be a real backend response.
export const server = setupServer();
