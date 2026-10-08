import { useQuery } from '@tanstack/react-query';
import { authApi } from '../../api/endpoints';

/** Public sign-in settings (sign-up allowed? demo accounts? where codes go?). */
export function useAuthConfig() {
  return useQuery({ queryKey: ['auth-config'], queryFn: authApi.config, staleTime: 60_000 });
}
