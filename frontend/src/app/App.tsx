import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../lib/api";
import { useSession } from "../stores/session";
import { LobbyPage } from "../features/rooms/LobbyPage";
import { ProfileDialog } from "../components/ProfileDialog";
import { LoadingState, ErrorState } from "../components/ui/AsyncState";
import { ServerStatusBanner } from "../components/ServerStatusBanner";

export function App() {
  const queryClient = useQueryClient();
  const catalog = useQuery({ queryKey: ["catalog-status"], queryFn: () => api.catalogStatus().then((result) => result.data) });
  const setUser = useSession((state) => state.setUser);
  const [editingProfile, setEditingProfile] = useState(false);
  const identity = useQuery({
    queryKey: ["identity"], staleTime: Infinity,
    queryFn: async () => {
      try { return (await api.me()).data; }
      catch (error) {
        if (error instanceof ApiError && error.status === 401) return (await api.createGuest()).data;
        throw error; // Network/server failures must never replace an existing identity.
      }
    },
  });
  useEffect(() => { if (identity.data) setUser(identity.data); }, [identity.data, setUser]);
  if (identity.isPending) return <LoadingState label="Preparando seu vestiário…" />;
  if (identity.error || !identity.data) return <ErrorState message="Não foi possível conectar ao servidor. Sua identidade foi preservada. Confira a conexão e tente novamente." onRetry={() => void identity.refetch()} />;
  const saveProfile = async (name: string) => {
    const { data } = await api.updateMe(name);
    setUser(data);
    queryClient.setQueryData(["identity"], data);
    setEditingProfile(false);
  };
  const displayName = identity.data.display_name;
  const needsProfile = !displayName || displayName.startsWith("Técnico ");
  return <><ServerStatusBanner />{catalog.data?.demo && <div className="demo-banner" role="status">MODO DEMONSTRAÇÃO — atletas e valores sintéticos, exclusivo para testes.</div>}<LobbyPage needsProfile={needsProfile} onSaveProfile={saveProfile} onEditProfile={() => setEditingProfile(true)} />{editingProfile && !needsProfile && <ProfileDialog currentName={displayName} onClose={() => setEditingProfile(false)} onSave={saveProfile} />}</>;
}
