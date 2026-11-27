import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import CoveragePanel from './CoveragePanel';

describe('CoveragePanel', () => {
  it('renders only the limits that were actually recorded', () => {
    render(<CoveragePanel coverage={{ room_rent_limit: '1% of sum insured' }} />);

    expect(screen.getByText('Room rent limit')).toBeInTheDocument();
    expect(screen.getByText('1% of sum insured')).toBeInTheDocument();
    expect(screen.queryByText('ICU limit')).not.toBeInTheDocument();
    // No estimate is ever invented for a missing limit.
    expect(screen.queryByText(/not covered/i)).not.toBeInTheDocument();
  });

  it('states that nothing is recorded instead of filling in values', () => {
    render(<CoveragePanel coverage={{}} />);

    expect(screen.getByText(/No structured coverage recorded/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Only recorded values are shown/i)
    ).toBeInTheDocument();
  });

  it('shows the page and clause reference when the backend provides one', () => {
    render(
      <CoveragePanel
        coverage={{ icu_limit: '₹5,000 per day' }}
        fieldSources={{ icu_limit: { page: 4, clause: '3.2' } }}
      />
    );

    expect(screen.getByText(/page 4, clause 3.2/)).toBeInTheDocument();
  });
});
