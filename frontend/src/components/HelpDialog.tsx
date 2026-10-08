import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from '@mui/material';
import { Kbd } from './Kbd';

interface Props {
  open: boolean;
  onClose: () => void;
  shortcuts: { key: string; label: string }[];
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
}

export function HelpDialog({ open, onClose, shortcuts, enabled, onToggle }: Props) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Keyboard shortcuts</DialogTitle>
      <DialogContent>
        <Stack component="ul" spacing={1.25} sx={{ listStyle: 'none', p: 0, m: 0 }}>
          {[...shortcuts, { key: '?', label: 'Show this help' }].map((shortcut) => (
            <Stack key={shortcut.key} component="li" direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="body2">{shortcut.label}</Typography>
              <Kbd>{shortcut.key}</Kbd>
            </Stack>
          ))}
        </Stack>
        <Divider sx={{ my: 2 }} />
        <FormControlLabel
          control={<Switch checked={enabled} onChange={(e) => onToggle(e.target.checked)} />}
          label="Single-key shortcuts"
        />
        <Typography variant="caption" color="text.secondary" component="p">
          Shortcuts only work when you're not typing in a field.
        </Typography>
        <Box sx={{ mt: 2, p: 1.5, borderRadius: 2, bgcolor: 'grey.50' }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            Need a hand?
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Ask your administrator for access, approvals or a password reset.
          </Typography>
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button variant="contained" onClick={onClose}>
          Done
        </Button>
      </DialogActions>
    </Dialog>
  );
}
