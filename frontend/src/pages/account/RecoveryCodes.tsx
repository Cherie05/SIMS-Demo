import { useSnackbar } from 'notistack';
import { Alert, Box, Button, Stack } from '@mui/material';
import CopyIcon from '@mui/icons-material/ContentCopyOutlined';
import DownloadIcon from '@mui/icons-material/FileDownloadOutlined';

/** One-time display of recovery codes, with copy and download. */
export function RecoveryCodes({ codes }: { codes: string[] }) {
  const { enqueueSnackbar } = useSnackbar();
  const text = `SIMS recovery codes - each works once. Keep them somewhere safe.\n\n${codes.join('\n')}\n`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      enqueueSnackbar('Recovery codes copied', { variant: 'success' });
    } catch {
      enqueueSnackbar('Copy failed: select the codes and copy them manually', { variant: 'warning' });
    }
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'sims-recovery-codes.txt';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box>
      <Alert severity="warning" sx={{ mb: 2 }}>
        Save these codes now - they won't be shown again. Each one signs you in once if you lose your phone.
      </Alert>
      <Box
        component="ul"
        aria-label="Recovery codes"
        sx={{
          listStyle: 'none',
          p: 2,
          m: 0,
          display: 'grid',
          gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(2, 1fr)' },
          gap: 1,
          bgcolor: 'grey.50',
          borderRadius: 2,
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
          fontSize: 15,
        }}
      >
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </Box>
      <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
        <Button size="small" startIcon={<CopyIcon />} onClick={() => void copy()}>
          Copy
        </Button>
        <Button size="small" startIcon={<DownloadIcon />} onClick={download}>
          Download
        </Button>
      </Stack>
    </Box>
  );
}
