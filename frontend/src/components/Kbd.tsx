import { Box } from '@mui/material';
import { brand } from '../theme';

/** A keyboard key, e.g. the shortcut hints in the sidebar. */
export function Kbd({ children, hidden, hideOnSmall }: { children: string; hidden?: boolean; hideOnSmall?: boolean }) {
  return (
    <Box
      component="kbd"
      aria-hidden={hidden || undefined}
      sx={{
        minWidth: 22,
        height: 22,
        px: 0.5,
        // Sidebar hints are pointless on touch-sized screens; the help dialog always shows them.
        display: hideOnSmall ? { xs: 'none', md: 'inline-grid' } : 'inline-grid',
        placeItems: 'center',
        borderRadius: 1,
        border: `1px solid ${brand.lineStrong}`,
        bgcolor: '#ffffff',
        color: brand.muted,
        fontFamily: 'inherit',
        fontSize: 11,
        fontWeight: 600,
        lineHeight: 1,
      }}
    >
      {children}
    </Box>
  );
}
