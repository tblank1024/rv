import { IPADDR, PORT } from '../constants';

/**
 * Get the base server URL dynamically
 * This handles different deployment scenarios:
 * - Development: localhost
 * - LAN access: same IP as webpage
 * - Internet access: same domain as webpage
 */
export const getServerUrl = () => {
  if (IPADDR === 'auto' || IPADDR === 'localhost' || IPADDR === '127.0.0.1') {
    // Auto-detect: use the same host as the current page
    return `http://${window.location.hostname}:${PORT}`;
  }
  // Explicit IP address override
  return `http://${IPADDR}:${PORT}`;
};

/**
 * Fetch data from server endpoint with automatic URL resolution
 * @param {string} endpoint - API endpoint path (e.g., '/data/home')
 * @param {object} options - Fetch options
 */
export const fetchFromServer = async (endpoint, options = {}) => {
  const url = `${getServerUrl()}${endpoint}`;
  
  const defaultOptions = {
    method: "GET",
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    }
  };
  
  // Merge options, preserving any signal that might be passed in
  const fetchOptions = { ...defaultOptions, ...options };
  
  const response = await fetch(url, fetchOptions);
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return response.json();
};
