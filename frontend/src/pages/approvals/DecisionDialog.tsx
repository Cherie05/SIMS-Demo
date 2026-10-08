import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material';
import { ordersApi } from '../../api/endpoints';
import { getErrorCode, getErrorMessage } from '../../api/client';
import { formatMoney } from '../../utils/format';
import type { OrderListItem } from '../../types';

export type Decision = 'approve' | 'reject' | 'cancel';

const COPY: Record<Decision, { title: string; button: string; color: 'success' | 'error' | 'warning'; label: string }> =
  {
    approve: { title: 'Approve order', button: 'Approve & complete', color: 'success', label: 'Comment (optional)' },
    reject: { title: 'Reject order', button: 'Reject order', color: 'error', label: 'Reason for rejection' },
    cancel: { title: 'Cancel order', button: 'Cancel order', color: 'warning', label: 'Reason (optional)' },
  };

interface Props {
  order: Pick<OrderListItem, 'id' | 'order_number' | 'total_amount' | 'customer'> | null;
  decision: Decision | null;
  onClose: () => void;
}

/** Approve / reject / cancel an order awaiting approval. Rejection requires a reason. */
export function DecisionDialog({ order, decision, onClose }: Props) {
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const [comment, setComment] = useState('');
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setComment('');
    setTouched(false);
    setError(null);
  }, [order, decision]);

  const reasonRequired = decision === 'reject';
  const reasonInvalid = reasonRequired && comment.trim().length < 3;

  const mutation = useMutation({
    mutationFn: () => {
      if (!order || !decision) throw new Error('No order selected');
      if (decision === 'approve') return ordersApi.approve(order.id, comment.trim());
      if (decision === 'reject') return ordersApi.reject(order.id, comment.trim());
      return ordersApi.cancel(order.id, comment.trim());
    },
    onSuccess: (updated) => {
      ['orders', 'approvals', 'dashboard', 'products', 'inventory'].forEach((key) =>
        queryClient.invalidateQueries({ queryKey: [key] }),
      );
      queryClient.setQueryData(['order', updated.id], updated);
      // The notification email is sent in the background after the response; refresh to show it.
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['order', updated.id] }), 1500);
      const verb =
        decision === 'approve' ? 'approved — stock updated and order completed' : `${updated.status.toLowerCase()}`;
      enqueueSnackbar(`${updated.order_number} ${verb}`, { variant: decision === 'approve' ? 'success' : 'info' });
      onClose();
    },
    onError: (err) => {
      const message = getErrorMessage(err);
      setError(
        getErrorCode(err) === 'INSUFFICIENT_STOCK' ? `${message}. Restock the product or reject the order.` : message,
      );
    },
  });

  if (!decision) return null;
  const copy = COPY[decision];

  return (
    <Dialog open={Boolean(order)} onClose={mutation.isPending ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{copy.title}</DialogTitle>
      <DialogContent>
        {order && (
          <Box sx={{ mb: 2, p: 1.5, bgcolor: 'grey.50', borderRadius: 2 }}>
            <Typography variant="subtitle2">{order.order_number}</Typography>
            <Typography variant="body2" color="text.secondary">
              {order.customer.name} · {formatMoney(order.total_amount)}
            </Typography>
          </Box>
        )}
        {decision === 'approve' && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Stock is re-checked and deducted immediately, and the requester is notified by email.
          </Typography>
        )}
        {decision === 'reject' && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            No stock is deducted. The requester receives your reason by email.
          </Typography>
        )}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        <TextField
          label={copy.label}
          fullWidth
          multiline
          minRows={3}
          autoFocus
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          onBlur={() => setTouched(true)}
          required={reasonRequired}
          error={touched && reasonInvalid}
          helperText={touched && reasonInvalid ? 'Please give a reason (at least 3 characters)' : ' '}
          slotProps={{ htmlInput: { maxLength: 500 } }}
        />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={mutation.isPending}>
          Back
        </Button>
        <Button
          variant="contained"
          color={copy.color}
          disabled={mutation.isPending || reasonInvalid}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? 'Saving…' : copy.button}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
