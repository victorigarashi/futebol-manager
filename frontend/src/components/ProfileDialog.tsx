import { type FormEvent, useEffect, useState } from "react";
import { Modal } from "./Modal";

type ProfileDialogProps = {
  currentName: string;
  isPending?: boolean;
  onClose: () => void;
  onSave: (name: string) => Promise<void>;
};

export function ProfileDialog({ currentName, isPending, onClose, onSave }: ProfileDialogProps) {
  const [name, setName] = useState(currentName);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => setName(currentName), [currentName]);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = name.trim().replace(/\s+/g, " ");
    if (normalized.length < 3 || normalized.length > 24) return setError("Use entre 3 e 24 caracteres.");
    if (!/^[\p{L}\p{N} ]+$/u.test(normalized)) return setError("Use apenas letras, números e espaços.");
    setError("");
    setSaving(true);
    void onSave(normalized).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Não foi possível salvar o nome.")).finally(() => setSaving(false));
  };
  return <Modal className="profile-dialog" titleId="profile-title" onClose={onClose} closeDisabled={saving || isPending}><p className="section-kicker">SEU VESTIÁRIO</p><h2 id="profile-title">Como a galera vai te chamar?</h2><p>Esse é o nome que aparece para seus amigos na resenha.</p><form onSubmit={submit}><label>Nome do técnico<input autoFocus value={name} minLength={3} maxLength={24} onChange={(event) => setName(event.target.value)} /></label>{error && <p className="field-error" role="alert">{error}</p>}<button className="button-primary" disabled={saving || isPending}>{saving || isPending ? "Salvando…" : "Salvar nome"}</button></form></Modal>;
}
