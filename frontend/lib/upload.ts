import { API_BASE } from "./api";

export type UploadProgress = {
  loaded: number;
  total: number | null;
  percent: number | null;
};

export type UploadHandle<T> = {
  promise: Promise<T>;
  cancel: () => void;
};

export function uploadFormData<T>(
  path: string,
  formData: FormData,
  onProgress?: (progress: UploadProgress) => void,
): UploadHandle<T> {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<T>((resolve, reject) => {
    xhr.upload.onprogress = (event) => {
      const total = event.lengthComputable ? event.total : null;
      onProgress?.({
        loaded: event.loaded,
        total,
        percent: total ? Math.round((event.loaded / total) * 100) : null,
      });
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.responseText ? JSON.parse(xhr.responseText) as T : undefined as T);
        return;
      }
      try {
        const parsed = JSON.parse(xhr.responseText);
        reject(new Error(typeof parsed.detail === "string" ? parsed.detail : xhr.statusText));
      } catch {
        reject(new Error(xhr.statusText || "Upload failed"));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed"));
    xhr.onabort = () => reject(new Error("Upload cancelled"));
    xhr.open("POST", `${API_BASE}${path}`);
    xhr.withCredentials = true;
    xhr.send(formData);
  });
  return { promise, cancel: () => xhr.abort() };
}
