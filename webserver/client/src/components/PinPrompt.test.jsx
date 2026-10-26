/**
 * PinGate's branching, which is where the bug was: with no PIN set the server
 * reports configured:false + authenticated:true, and the gate passed straight
 * through -- so the setup flow inside PinPrompt existed but nothing could
 * reach it, and opening the debug page never offered to set a PIN.
 */
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { PinGate } from './PinPrompt';
import { fetchFromServer } from '../utils/api';

jest.mock('../utils/api', () => ({
  fetchFromServer: jest.fn(),
  getServerUrl: () => 'http://test',
}));

const authStatus = (overrides) => {
  fetchFromServer.mockResolvedValue({
    configured: false, authenticated: true, locked_out: false,
    retry_after: 0, expires_in: null, can_set_pin: true, ...overrides,
  });
};

const gate = () => render(<PinGate><div>SECRET PANEL</div></PinGate>);

test('no PIN set, on the RV LAN: offers to choose one', async () => {
  authStatus({ configured: false, authenticated: true, can_set_pin: true });
  gate();
  await waitFor(() => expect(screen.getByText(/Choose a PIN/i)).toBeInTheDocument());
  expect(screen.queryByText('SECRET PANEL')).not.toBeInTheDocument();
});

test('no PIN set, off the RV LAN: does not block, since it cannot be set here', async () => {
  authStatus({ configured: false, authenticated: true, can_set_pin: false });
  gate();
  await waitFor(() => expect(screen.getByText('SECRET PANEL')).toBeInTheDocument());
});

test('PIN set, untrusted device: asks for it', async () => {
  authStatus({ configured: true, authenticated: false });
  gate();
  await waitFor(() => expect(screen.getByText(/Enter the PIN/i)).toBeInTheDocument());
  expect(screen.queryByText('SECRET PANEL')).not.toBeInTheDocument();
});

test('PIN set, trusted device: lets the panel through', async () => {
  authStatus({ configured: true, authenticated: true });
  gate();
  await waitFor(() => expect(screen.getByText('SECRET PANEL')).toBeInTheDocument());
});

test('server unreachable: fails closed rather than exposing the panel', async () => {
  fetchFromServer.mockRejectedValue(new Error('network down'));
  gate();
  await waitFor(() => expect(screen.getByText(/Enter the PIN/i)).toBeInTheDocument());
  expect(screen.queryByText('SECRET PANEL')).not.toBeInTheDocument();
});


// ---------------------------------------------------------------------------
// Setting the PIN, driven only by the keypad.
//
// This is what was broken: the confirmation used to be a text input, so on
// the wall tablet -- which has no keyboard -- it could not be filled in at
// all. Setup is now two passes on the same keypad, and these tests press the
// keys rather than trusting that they work.
// ---------------------------------------------------------------------------

const tapDigits = (digits) => {
  for (const d of digits) {
    fireEvent.click(screen.getByRole('button', { name: d }));
  }
};

describe('setting a PIN with no keyboard', () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      status: 200, ok: true, json: async () => ({ success: true }),
    });
  });

  test('two keypad passes set the PIN', async () => {
    authStatus({ configured: false, can_set_pin: true });
    gate();
    await waitFor(() => expect(screen.getByText(/Choose a PIN/i)).toBeInTheDocument());

    tapDigits('8471');
    // Four taps, four dots, and no keyboard involved anywhere.
    expect(screen.getByText('••••')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }));
    await waitFor(() => expect(screen.getByText(/Re-enter the PIN/i)).toBeInTheDocument());

    tapDigits('8471');
    fireEvent.click(screen.getByRole('button', { name: /^Set PIN$/ }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain('/api/auth/setup');
    expect(JSON.parse(options.body)).toEqual({ pin: '8471' });
  });

  test('a mismatch starts over instead of saving a typo', async () => {
    authStatus({ configured: false, can_set_pin: true });
    gate();
    await waitFor(() => expect(screen.getByText(/Choose a PIN/i)).toBeInTheDocument());

    tapDigits('8471');
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }));
    await waitFor(() => expect(screen.getByText(/Re-enter the PIN/i)).toBeInTheDocument());

    tapDigits('8472');
    fireEvent.click(screen.getByRole('button', { name: /^Set PIN$/ }));

    await waitFor(() => expect(screen.getByText(/did not match/i)).toBeInTheDocument());
    // Back at the first pass with nothing entered, and nothing was sent.
    expect(screen.getByText(/Choose a PIN/i)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('backspace removes a digit', async () => {
    authStatus({ configured: false, can_set_pin: true });
    gate();
    await waitFor(() => expect(screen.getByText(/Choose a PIN/i)).toBeInTheDocument());

    tapDigits('847');
    expect(screen.getByText('•••')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '⌫' }));
    expect(screen.getByText('••')).toBeInTheDocument();
  });

  test('Next is refused below four digits', async () => {
    authStatus({ configured: false, can_set_pin: true });
    gate();
    await waitFor(() => expect(screen.getByText(/Choose a PIN/i)).toBeInTheDocument());

    tapDigits('84');
    expect(screen.getByRole('button', { name: /^Next$/ })).toBeDisabled();
    tapDigits('71');
    expect(screen.getByRole('button', { name: /^Next$/ })).not.toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// SecurityCard: the change and forget flows, which exist because the
// endpoints were previously reachable only by curl.
// ---------------------------------------------------------------------------
describe('SecurityCard', () => {
  let SecurityCard;
  beforeEach(() => {
    SecurityCard = require('./SecurityCard').default;
    global.fetch = jest.fn().mockResolvedValue({
      status: 200, ok: true, json: async () => ({ success: true, message: 'PIN changed.' }),
    });
  });

  test('three keypad passes change the PIN', async () => {
    authStatus({ configured: true, authenticated: true, expires_in: 2592000 });
    render(<SecurityCard />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Change PIN' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Change PIN' }));
    await waitFor(() => expect(screen.getByText('Enter the current PIN')).toBeInTheDocument());
    tapDigits('8471');
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }));

    await waitFor(() => expect(screen.getByText('Enter the new PIN')).toBeInTheDocument());
    tapDigits('1234');
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }));

    await waitFor(() => expect(screen.getByText('Re-enter the new PIN')).toBeInTheDocument());
    tapDigits('1234');
    fireEvent.click(screen.getByRole('button', { name: 'Change PIN' }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain('/api/auth/change');
    expect(JSON.parse(options.body)).toEqual({ current: '8471', new: '1234' });
  });

  test('mismatched new PINs go back to the new-PIN pass and send nothing', async () => {
    authStatus({ configured: true, authenticated: true, expires_in: 2592000 });
    render(<SecurityCard />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Change PIN' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Change PIN' }));
    tapDigits('8471');
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }));
    tapDigits('1234');
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }));
    tapDigits('9999');
    fireEvent.click(screen.getByRole('button', { name: 'Change PIN' }));

    await waitFor(() => expect(screen.getByText(/did not match/i)).toBeInTheDocument());
    expect(screen.getByText('Enter the new PIN')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('forget all devices confirms before sending', async () => {
    authStatus({ configured: true, authenticated: true, expires_in: 2592000 });
    render(<SecurityCard />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Forget all devices' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Forget all devices' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Yes, sign all out/i })).toBeInTheDocument());
    expect(global.fetch).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Yes, sign all out/i }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(global.fetch.mock.calls[0][0]).toContain('/api/auth/revoke-all');
  });

  test('with no PIN set it offers to set one instead', async () => {
    authStatus({ configured: false, authenticated: true, can_set_pin: true });
    render(<SecurityCard />);
    await waitFor(() => expect(screen.getByText('No PIN set')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Change PIN' })).not.toBeInTheDocument();
  });
});
