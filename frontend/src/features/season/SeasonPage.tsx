import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { CareerShell, type CareerChrome } from "../career/CareerShell";
import "./season-beta.css";

/** In-season entry point: the multiplayer career mode shell. */
export function SeasonPage({ roomId, isHost, clubCode, chrome }: { roomId: string; isHost: boolean; clubCode: string; chrome?: CareerChrome }) {
  const room = useQuery({ queryKey: ["room-state", roomId], queryFn: () => api.state(roomId).then(({ data }) => data) });
  if (!room.data) return <p className="panel-loading" role="status">{room.error ? room.error.message : "Abrindo a carreira…"}</p>;
  return <CareerShell roomId={roomId} room={room.data} isHost={isHost} clubCode={clubCode} chrome={chrome} />;
}
