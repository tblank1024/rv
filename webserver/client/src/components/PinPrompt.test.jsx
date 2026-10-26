/**
 * PinGate's branching, which is where the bug was: with no PIN set the server
 * reports configured:false + authenticated:true, and the gate passed straight
 * through -- so the setup flow inside PinPrompt existed but nothing could
 * reach it, and opening the debug page never offered to set a PIN.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
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
