export type ApiError = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

export type ApiResponse<T> = {
  data: T | null;
  error: ApiError | null;
  requestId: string;
};
