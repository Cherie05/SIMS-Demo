import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Product } from '../../types';
import { StockAdjustDialog } from './StockAdjustDialog';

const adjustStock = vi.hoisted(() => vi.fn());
vi.mock('../../api/endpoints', () => ({ productsApi: { adjustStock } }));
vi.mock('notistack', () => ({ useSnackbar: () => ({ enqueueSnackbar: vi.fn() }) }));

const product: Product = {
  id: 1,
  sku: 'STOCK-001',
  name: 'Test product',
  description: null,
  unit_price: 25,
  stock_qty: 10,
  reorder_level: 5,
  is_active: true,
  is_low_stock: false,
  created_at: '2026-10-07T00:00:00Z',
  updated_at: '2026-10-07T00:00:00Z',
};

function Harness() {
  const [selected, setSelected] = useState<Product | null>(product);
  return (
    <>
      <button onClick={() => setSelected({ ...product, stock_qty: 15 })}>Adjust again</button>
      <StockAdjustDialog product={selected} onClose={() => setSelected(null)} />
    </>
  );
}

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

describe('StockAdjustDialog', () => {
  beforeEach(() => {
    adjustStock.mockReset();
  });

  it('uses a new idempotency key for another identical restock after a confirmed success', async () => {
    adjustStock.mockResolvedValue({ product, balance_after: 15 });
    const user = renderDialog();
    await user.type(screen.getByLabelText('Quantity'), '5');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Adjust again' }));
    await user.type(screen.getByLabelText('Quantity'), '5');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(adjustStock).toHaveBeenCalledTimes(2));

    const [first, second] = adjustStock.mock.calls;
    expect(first.slice(0, 2)).toEqual(second.slice(0, 2));
    expect(first[2]).toEqual(expect.any(String));
    expect(second[2]).not.toBe(first[2]);
  });

  it('reuses the same idempotency key when retrying an uncertain failed response', async () => {
    adjustStock
      .mockRejectedValueOnce(new Error('The server took too long to respond'))
      .mockResolvedValueOnce({ product, balance_after: 15 });
    const user = renderDialog();
    await user.type(screen.getByLabelText('Quantity'), '5');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The server took too long to respond');

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(adjustStock).toHaveBeenCalledTimes(2));
    expect(adjustStock.mock.calls[1]).toEqual(adjustStock.mock.calls[0]);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
