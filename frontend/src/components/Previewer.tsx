import { useEffect, useMemo, useRef, useState } from "react";
import { FileCard } from "@ant-design/x";
import {
  CloseOutlined,
  DownloadOutlined,
  FileExcelOutlined,
  FileTextOutlined,
  PlusOutlined,
} from "@ant-design/icons";

import { ACCEPTED_EXTENSIONS } from "../domain/models";
import { useAppStore } from "../hooks/useAppStore";
import { SpreadsheetPreview } from "./SpreadsheetPreview";
import { api } from "../api/httpClient";
import type { Tab } from "../domain/workflow";

const ACCEPT = ACCEPTED_EXTENSIONS.join(",");

export function Previewer() {
  const currentSessionId = useAppStore((s) => s.currentSessionId);
  const tabsBySession = useAppStore((s) => s.tabsBySession);
  const activeTabBySession = useAppStore((s) => s.activeTabBySession);
  const filePreviews = useAppStore((s) => s.filePreviews);
  const outputPreviews = useAppStore((s) => s.outputPreviews);
  const previewError = useAppStore((s) => s.previewError);
  const status = useAppStore((s) => s.status);
  const removeFile = useAppStore((s) => s.removeFile);
  const removeTab = useAppStore((s) => s.removeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const uploadFile = useAppStore((s) => s.uploadFile);
  const addEmptyTab = useAppStore((s) => s.addEmptyTab);

  const tabs = currentSessionId ? tabsBySession[currentSessionId] ?? [] : [];
  const activeTabId = currentSessionId ? activeTabBySession[currentSessionId] ?? "" : "";

  const [activeSheet, setActiveSheet] = useState<string | null>(null);
  const uploaderDisabled = status === "uploading" || status === "processing";
  const fileInputRef = useRef<HTMLInputElement>(null);

  const activeTab: Tab | null = useMemo(
    () => tabs.find((t) => t.id === activeTabId) ?? null,
    [tabs, activeTabId],
  );

  const activePreview = useMemo(() => {
    if (!activeTab) return null;
    if (activeTab.kind === "file") return filePreviews[activeTab.refId] ?? null;
    return outputPreviews[activeTab.refId] ?? null;
  }, [activeTab, filePreviews, outputPreviews]);

  useEffect(() => {
    setActiveSheet(activePreview?.sheets[0]?.name ?? null);
  }, [activePreview]);

  const downloadHref = useMemo(() => {
    if (activeTab?.kind === "output") return api.downloadUrl(activeTab.refId);
    return null;
  }, [activeTab]);

  const activeTabIsEmpty = activeTab?.kind === "file" && activeTab.refId === "";

  const emptyDropzone = (
    <div className="empty-state previewer-empty" data-testid="previewer-empty-dropzone">
      <p className="empty-title">点击或拖入文件</p>
      <p className="empty-sub">支持 Excel / CSV，单文件</p>
      <FileCard
        name="empty-dropzone"
        className="previewer-dropzone"
        role="button"
        tabIndex={0}
        data-testid="upload-dropzone"
        onClick={() => fileInputRef.current?.click()}
      >
        <div className="dropzone-inner">
          <div className="dropzone-icon">+</div>
          <div className="dropzone-hint">选择文件</div>
        </div>
      </FileCard>
    </div>
  );

  return (
    <div className="previewer">
      <div className="tab-bar" data-testid="tab-bar">
        {tabs.length === 0 ? (
          <span className="tab-bar-placeholder">暂无打开的文件</span>
        ) : (
          tabs.map((t) => {
            const isActive = t.id === activeTabId;
            return (
              <div
                key={t.id}
                className={`tab-item ${isActive ? "is-active" : ""}`}
                role="tab"
                aria-selected={isActive}
                data-testid="tab-item"
              >
                <button
                  type="button"
                  className="tab-item-label"
                  onClick={() => currentSessionId && setActiveTab(currentSessionId, t.id)}
                  title={t.fileName}
                >
                  {t.kind === "output" ? <FileTextOutlined /> : <FileExcelOutlined />}
                  <span className="tab-item-name">{t.fileName}</span>
                </button>
                <button
                  type="button"
                  className="tab-item-close"
                  aria-label="关闭标签"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (currentSessionId) removeTab(currentSessionId, t.id);
                    if (t.kind === "file") removeFile(t.refId);
                  }}
                >
                  <CloseOutlined />
                </button>
              </div>
            );
          })
        )}
        <button
          type="button"
          className="tab-add-btn"
          onClick={() => currentSessionId && addEmptyTab(currentSessionId)}
          disabled={uploaderDisabled}
          aria-label="新增标签"
          data-testid="tab-add-btn"
        >
          <PlusOutlined />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT}
          hidden
          data-testid="tab-add-input"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void uploadFile(file);
            e.target.value = "";
          }}
        />
      </div>

      <div className="previewer-body">
        {previewError && <div className="previewer-warning">{previewError}</div>}
        {tabs.length === 0 && (
          <div className="empty-state previewer-empty">
            <p className="empty-title">暂无打开的文件</p>
            <p className="empty-sub">点击右上角 + 新增标签，或直接拖入文件</p>
            <button
              type="button"
              className="empty-action-btn"
              onClick={() => currentSessionId && addEmptyTab(currentSessionId)}
              data-testid="empty-add-tab"
            >
              <PlusOutlined /> 新增标签
            </button>
          </div>
        )}
        {activeTabIsEmpty && emptyDropzone}
        {tabs.length > 0 && activePreview && !activeTabIsEmpty && (
          <SpreadsheetPreview
            preview={activePreview}
            activeSheet={activeSheet}
            onSheetChange={setActiveSheet}
            onDownload={
              downloadHref
                ? () => {
                    window.open(downloadHref, "_blank");
                  }
                : undefined
            }
          />
        )}
        {tabs.length > 0 && !activePreview && !activeTabIsEmpty && (
          <div className="empty-state previewer-empty">
            <p className="empty-title">{activeTab?.fileName ?? "加载中"}</p>
            <p className="empty-sub">正在解析该文件…</p>
          </div>
        )}
        {downloadHref && (
          <a
            className="previewer-download-fab"
            href={downloadHref}
            download
            data-testid="previewer-download"
          >
            <DownloadOutlined />
            <span>下载 Excel</span>
          </a>
        )}
      </div>
    </div>
  );
}