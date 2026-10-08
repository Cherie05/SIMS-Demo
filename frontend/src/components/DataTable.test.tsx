import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DataTable } from './DataTable';

const row = { id: 1, name: 'Order 001' };
const columns = [{ key: 'name', header: 'Order', render: (value: typeof row) => value.name }];

describe('DataTable', () => {
  it('opens an interactive row with the keyboard and leaves child controls independent', () => {
    const open = vi.fn();
    render(<DataTable rows={[row]} columns={columns} rowKey={(value) => value.id} onRowClick={open} />);
    const interactiveRow = screen.getByText(row.name).closest('tr')!;
    expect(interactiveRow).toHaveAttribute('tabindex', '0');
    fireEvent.keyDown(interactiveRow, { key: 'Enter' });
    expect(open).toHaveBeenCalledWith(row);
    open.mockClear();
    fireEvent.keyDown(screen.getByText(row.name), { key: 'Enter' });
    expect(open).not.toHaveBeenCalled();
  });

  it('shows a retryable error without claiming the data set is empty', () => {
    const retry = vi.fn();
    render(
      <DataTable
        rows={[]}
        columns={columns}
        rowKey={(value) => value.id}
        error="Service unavailable"
        onRetry={retry}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Service unavailable');
    expect(screen.queryByText('Nothing to show yet')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('supports the current page size and hides an unavailable page-size selector', () => {
    const { rerender } = render(
      <DataTable
        rows={[row]}
        columns={columns}
        rowKey={(value) => value.id}
        total={100}
        pageSize={25}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveTextContent('25');
    rerender(
      <DataTable
        rows={[row]}
        columns={columns}
        rowKey={(value) => value.id}
        total={100}
        pageSize={10}
        onPageChange={vi.fn()}
      />,
    );
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});
