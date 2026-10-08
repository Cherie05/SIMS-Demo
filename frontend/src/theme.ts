import { alpha, createTheme } from '@mui/material/styles';

/** Design tokens. UI chrome uses `brand`; data marks use the validated `chart` palette. */
export const brand = {
  // 4.9:1 on white, and white text on it: passes WCAG AA for normal-size text both ways.
  teal: '#0e7f72',
  tealDark: '#0a645a',
  tealSoft: '#e6f4f1',
  ink: '#1c2625',
  ink2: '#5d6968',
  muted: '#66706f',
  line: '#e8ecea',
  lineStrong: '#d9dfdd',
  sidebar: '#f6f7f7',
  sidebarActive: '#e8ecea',
  hover: '#eff2f1',
  danger: '#c93c3c', // 5:1 on white
  dangerSoft: '#fdeeee',
  warning: '#a8620a',
  warningSoft: '#fdf3e2',
  successSoft: '#e3f5f0',
  badge: '#e5484d',
};

/**
 * Categorical slots for order statuses, checked with the dataviz palette validator
 * (lightness band, chroma, colour-blind separation); amber sits below 3:1 on white, so every
 * chart that uses it also shows labelled values.
 */
export const chart = {
  series: '#16a08f',
  amber: '#eaa21c',
  red: '#d9534f',
  violet: '#7480e0',
  context: '#9aa5a3',
  grid: '#eef1f0',
  axis: '#66706f',
  track: '#edf1ef',
  surface: '#ffffff',
};

export const theme = createTheme({
  palette: {
    primary: { main: brand.teal, dark: brand.tealDark, light: '#3fa597', contrastText: '#ffffff' },
    secondary: { main: '#5b6bd6' },
    background: { default: '#ffffff', paper: '#ffffff' },
    success: { main: '#0e7f72' },
    warning: { main: '#c27a0e' },
    error: { main: brand.danger },
    info: { main: '#3d6fd6' },
    text: { primary: brand.ink, secondary: brand.ink2, disabled: '#a7b0af' },
    divider: brand.line,
    action: { hover: brand.hover, selected: brand.sidebarActive },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"DM Sans Variable", "DM Sans", Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    h4: { fontWeight: 700, fontSize: '1.55rem', letterSpacing: '-0.015em' },
    h5: { fontWeight: 700, fontSize: '1.65rem', letterSpacing: '-0.02em' },
    h6: { fontWeight: 700, fontSize: '1.05rem' },
    subtitle1: { fontWeight: 600, fontSize: '1rem' },
    subtitle2: { fontWeight: 600 },
    body2: { fontSize: '0.875rem' },
    button: { textTransform: 'none', fontWeight: 600, letterSpacing: 0 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { backgroundColor: '#ffffff', WebkitFontSmoothing: 'antialiased' },
        '::selection': { background: alpha(brand.teal, 0.18) },
      },
    },
    MuiTypography: {
      // Visual variants map to a proper document outline: page title h1, section titles h2.
      defaultProps: { variantMapping: { h4: 'h1', h5: 'p', h6: 'p', subtitle1: 'h2', subtitle2: 'p' } },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: { border: `1px solid ${brand.line}`, boxShadow: '0 1px 2px rgba(16, 24, 40, 0.04)' },
        rounded: { borderRadius: 12 },
      },
    },
    MuiAppBar: { styleOverrides: { root: { border: 'none', boxShadow: 'none' } } },
    MuiDrawer: { styleOverrides: { paper: { border: 'none', boxShadow: 'none' } } },
    MuiMenu: {
      styleOverrides: { paper: { boxShadow: '0 12px 32px rgba(16, 24, 40, 0.12)', borderRadius: 12 } },
    },
    MuiPopover: { styleOverrides: { paper: { boxShadow: '0 12px 32px rgba(16, 24, 40, 0.12)' } } },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 8, paddingInline: 14 },
        sizeLarge: { minHeight: 46, fontSize: '0.95rem' },
        outlined: { borderColor: brand.lineStrong, '&:hover': { borderColor: '#c3cbc9' } },
        outlinedInherit: { borderColor: brand.lineStrong },
      },
    },
    MuiIconButton: { styleOverrides: { root: { borderRadius: 8 } } },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          backgroundColor: '#ffffff',
          '& .MuiOutlinedInput-notchedOutline': { borderColor: brand.lineStrong },
          '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: '#b9c2c0' },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderBottom: `1px solid ${brand.line}` },
        head: {
          fontWeight: 600,
          fontSize: '0.8rem',
          color: brand.ink2,
          backgroundColor: '#f8faf9',
          whiteSpace: 'nowrap',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          '&.MuiTableRow-hover:hover': { backgroundColor: alpha(brand.teal, 0.035) },
          '&:last-child td': { borderBottom: 0 },
        },
      },
    },
    MuiChip: { styleOverrides: { root: { fontWeight: 600, borderRadius: 6 } } },
    MuiTab: { styleOverrides: { root: { textTransform: 'none', fontWeight: 600, minHeight: 44 } } },
    MuiTabs: { styleOverrides: { indicator: { height: 3, borderRadius: 3 } } },
    MuiTooltip: {
      styleOverrides: { tooltip: { backgroundColor: brand.ink, fontSize: 12, borderRadius: 6, padding: '6px 10px' } },
    },
    MuiDialog: { styleOverrides: { paper: { borderRadius: 16 } } },
    MuiDialogTitle: { styleOverrides: { root: { fontWeight: 700, fontSize: '1.15rem' } } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 10 } } },
    MuiToggleButton: { styleOverrides: { root: { textTransform: 'none', fontWeight: 600 } } },
    MuiLinearProgress: { styleOverrides: { root: { borderRadius: 4 } } },
  },
});
