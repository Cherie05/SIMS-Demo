import {
  Alert,
  Box,
  Button,
  LinearProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Typography,
} from '@mui/material';
import { visuallyHidden } from '@mui/utils';
import type { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  align?: 'left' | 'right' | 'center';
  width?: number | string;
  hideOnMobile?: boolean;
}

interface Props<T> {
  rows: T[] | undefined;
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
  total?: number;
  page?: number; // 0-based
  pageSize?: number;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  onRowClick?: (row: T) => void;
  emptyText?: string;
  /** Accessible name for the scrollable table region. */
  label?: string;
  toolbar?: ReactNode;
}

/** Table with server-side pagination, loading bar and empty state. */
export function DataTable<T>({
  rows,
  columns,
  rowKey,
  loading,
  error,
  onRetry,
  total,
  page = 0,
  pageSize = 20,
  onPageChange,
  onPageSizeChange,
  onRowClick,
  emptyText = 'Nothing to show yet',
  label = 'Table',
  toolbar,
}: Props<T>) {
  const mobileHidden = { display: { xs: 'none', md: 'table-cell' } };
  return (
    <Paper sx={{ overflow: 'hidden' }}>
      {toolbar && <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>{toolbar}</Box>}
      {error && (
        <Alert
          severity="error"
          action={
            onRetry ? (
              <Button color="inherit" size="small" onClick={onRetry}>
                Retry
              </Button>
            ) : undefined
          }
        >
          {error}
        </Alert>
      )}
      <Box sx={{ height: 4 }}>{loading && <LinearProgress />}</Box>
      {/* position: relative contains the visually-hidden header text inside the scroll area */}
      <TableContainer
        tabIndex={0}
        role="region"
        aria-label={label}
        aria-busy={Boolean(loading)}
        sx={{ position: 'relative' }}
      >
        <Table size="small">
          <TableHead>
            <TableRow>
              {columns.map((col) => (
                <TableCell
                  key={col.key}
                  align={col.align}
                  sx={{ width: col.width, py: 1.5, ...(col.hideOnMobile ? mobileHidden : {}) }}
                >
                  {col.header === '' ? (
                    <Box component="span" sx={visuallyHidden}>
                      Actions
                    </Box>
                  ) : (
                    col.header
                  )}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows?.map((row) => (
              <TableRow
                key={rowKey(row)}
                hover
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
                          event.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                sx={{
                  cursor: onRowClick ? 'pointer' : 'default',
                  '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 },
                }}
              >
                {columns.map((col) => (
                  <TableCell
                    key={col.key}
                    align={col.align}
                    sx={{ py: 1.25, ...(col.hideOnMobile ? mobileHidden : {}) }}
                  >
                    {col.render(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {rows && rows.length === 0 && !loading && !error && (
              <TableRow>
                <TableCell colSpan={columns.length}>
                  <Typography color="text.secondary" align="center" sx={{ py: 5 }}>
                    {emptyText}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
      {onPageChange && total !== undefined && (
        <TablePagination
          component="div"
          count={total}
          page={page}
          rowsPerPage={pageSize}
          rowsPerPageOptions={onPageSizeChange ? [...new Set([10, 20, 25, 50, pageSize])].sort((a, b) => a - b) : []}
          onPageChange={(_, p) => onPageChange(p)}
          onRowsPerPageChange={(e) => onPageSizeChange?.(parseInt(e.target.value, 10))}
        />
      )}
    </Paper>
  );
}
